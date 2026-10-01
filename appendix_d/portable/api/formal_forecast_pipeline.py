"""Connect an approved inventory registration to a formal local forecast run."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from forecast_provider.inventory_forecast_bridge import (
    SqliteInventoryForecastBridgeStore,
    build_inventory_forecast_bridge,
)

from .business_archive import _business_date, _center_and_file_date
from .forecast import forecast
from .formal_pipeline import PortableFormalPipeline
from .formal_pipeline_contracts import FormalPipelineError
from .formal_shipment_daily import (
    FormalShipmentBuildError,
    build_daily_shipment,
    canonical_json,
    daily_csv,
    sha256,
)

FORECAST_HORIZON = 14


class FormalForecastError(ValueError):
    pass


class PortableFormalForecastPipeline:
    def __init__(self, paths) -> None:
        self.paths = paths
        self.root = paths.formal_forecast
        self.root.mkdir(parents=True, exist_ok=True)
        self.inventory_pipeline = PortableFormalPipeline(paths)
        self.inventory_store = self.inventory_pipeline.inventory_store
        self.bridge_store = SqliteInventoryForecastBridgeStore(
            paths.state / "formal-pipeline.sqlite3"
        )

    def view(self, registration_id: str) -> dict:
        registration = self.inventory_pipeline.get_registration(registration_id)
        inventory_view = self.inventory_pipeline.registration_view(registration)
        proposal = self._identity_proposal(registration, inventory_view)
        latest = self._latest(registration_id)
        return {
            "registration_id": registration_id,
            "inventory_status": inventory_view["status"],
            "identity_proposal": proposal,
            "latest": latest,
        }

    def run(self, registration_id: str, payload: dict) -> dict:
        registration = self.inventory_pipeline.get_registration(registration_id)
        inventory_view = self.inventory_pipeline.registration_view(registration)
        if inventory_view["status"] != "APPROVED":
            raise FormalForecastError("すべての正式在庫Snapshotを承認してください")
        actor = str(payload.get("actor") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        if not actor or not reason:
            raise FormalForecastError("確認者と確認理由を入力してください")
        if payload.get("confirm_identity_bridge") is not True:
            raise FormalForecastError("JAN・倉庫の予測対応を確認してください")
        if payload.get("confirm_zero_policy") is not True:
            raise FormalForecastError("出荷0日の扱いを確認してください")
        proposal = self._identity_proposal(registration, inventory_view)
        created_at = datetime.now(UTC)
        bridge = build_inventory_forecast_bridge(
            records=[
                (
                    item["jan"], item["warehouse_id"], item["canonical_product_id"],
                    item["forecast_center_id"], date.fromisoformat(item["effective_from"]), None,
                )
                for item in proposal
            ],
            created_by=actor,
            reason=reason,
            created_at=created_at,
        )
        self.bridge_store.put(bridge)
        handoff = self.inventory_pipeline.get_handoff(registration["handoff_id"])
        analysis_id = handoff["analysis_id"]
        report = json.loads(
            (self.paths.analysis / f"{analysis_id}.json").read_text(encoding="utf-8")
        )
        invalid_occurrences, invalid_file_dates = _shipment_issue_evidence(report)
        reviewed = self.paths.prepared / f"{analysis_id}-reviewed.csv"
        prepared = reviewed if reviewed.is_file() else self.paths.prepared / f"{analysis_id}.csv"
        inventory_cases, snapshot_dates = self._inventory_context(
            registration, inventory_view
        )
        build, frame = build_daily_shipment(
            archive_path=self.paths.input / f"{analysis_id}.zip",
            prepared_path=prepared,
            handoff=handoff,
            registration_id=registration_id,
            identities=proposal,
            zero_when_file_present=True,
            snapshot_dates_by_center=snapshot_dates,
            invalid_occurrences=invalid_occurrences,
            invalid_file_dates=invalid_file_dates,
        )
        target = self.root / build["build_id"]
        manifest_path = target / "manifest.json"
        if manifest_path.is_file():
            return self._verified_result(manifest_path)
        daily_bytes = daily_csv(build)
        predictions: list[dict] = []
        if not frame.empty:
            for center, center_frame in frame.groupby("source_center", sort=True):
                predictions.extend(
                    forecast(
                        center_frame.drop(columns=["source_center"]),
                        self.paths.state,
                        f"{build['build_id']}-{center}",
                        horizon=FORECAST_HORIZON,
                        dataset_snapshot_id=build["build_id"],
                        selection_version=bridge.version.bridge_version,
                    )
                )
            predictions.sort(key=lambda item: (item["unique_id"], item["target_date"]))
        for row in predictions:
            row["current_inventory_cases"] = inventory_cases.get(row["unique_id"])
        result_bytes = canonical_json(predictions)
        target.mkdir(parents=True, exist_ok=True)
        daily_path = target / "daily.csv"
        self._atomic_bytes(daily_path, daily_bytes)
        self._atomic_bytes(target / "predictions.json", result_bytes)
        status = (
            "FORECAST_COMPLETED_WITH_BLOCKERS"
            if predictions and build["blocked_series_count"]
            else "FORECAST_COMPLETED" if predictions else "BLOCKED"
        )
        result = {
            "format": "portable-formal-forecast-pipeline-v1",
            "registration_id": registration_id,
            "build_id": build["build_id"],
            "status": status,
            "actor": actor,
            "reason": reason,
            "created_at": created_at.isoformat(),
            "identity_bridge_version": bridge.version.bridge_version,
            "inventory_snapshot_ids": sorted(
                item["snapshot_id"] for item in inventory_view["jobs"] if item["snapshot_id"]
            ),
            "source_archive_sha256": handoff["source_archive_sha256"],
            "prepared_sha256": build["prepared_sha256"],
            "daily_data_sha256": sha256(daily_bytes),
            "prediction_sha256": sha256(result_bytes),
            "train_start": build["train_start"],
            "train_end": build["train_end"],
            "center_windows": build["center_windows"],
            "horizon_days": FORECAST_HORIZON,
            "eligible_series_count": build["eligible_series_count"],
            "blocked_series_count": build["blocked_series_count"],
            "series": build["series"],
            "predictions": predictions,
            "notice": (
                "確認済み出荷履歴から14日予測を作成しました。試験運用の参考結果です。"
                if predictions
                else "履歴不足または欠測があるため予測対象はありません。"
            ),
        }
        self._atomic_json(manifest_path, result)
        return result

    def result_path(self, build_id: str) -> Path:
        if not build_id.startswith("portable-daily-") or len(build_id) != 79:
            raise FormalForecastError("予測結果が見つかりません")
        path = self.root / build_id / "predictions.json"
        if not path.is_file():
            raise FormalForecastError("予測結果が見つかりません")
        manifest = self._verified_result(path.with_name("manifest.json"))
        if manifest["build_id"] != build_id:
            raise FormalForecastError("予測結果の整合性を確認できません")
        return path

    def _identity_proposal(self, registration: dict, inventory_view: dict) -> list[dict]:
        handoff = self.inventory_pipeline.get_handoff(registration["handoff_id"])
        locations = {item["source_center"]: item for item in handoff["locations"]}
        proposal: list[dict] = []
        seen = set()
        for job in inventory_view["jobs"]:
            if job["status"] != "APPROVED" or not job["snapshot_id"]:
                continue
            location = locations[job["source_center"]]
            snapshot = self.inventory_store.get_snapshot(job["snapshot_id"])
            if snapshot is None:
                raise FormalForecastError("承認済み在庫Snapshotが見つかりません")
            effective = datetime.fromisoformat(snapshot["snapshot_at"]).date().isoformat()
            for bucket in self.inventory_store.list_expiry_buckets_with_location(
                job["snapshot_id"]
            ):
                if (
                    bucket["location_code"] != location["location_code"]
                    or bucket["normalized_unit"] != "CASE"
                    or bucket["issue_codes"]
                ):
                    continue
                key = (bucket["jan"], location["location_id"])
                if key in seen:
                    continue
                seen.add(key)
                proposal.append(
                    {
                        "source_center": job["source_center"],
                        "jan": bucket["jan"],
                        "warehouse_id": location["location_id"],
                        "canonical_product_id": bucket["jan"],
                        "forecast_center_id": location["location_code"],
                        "effective_from": effective,
                    }
                )
        if not proposal:
            raise FormalForecastError("承認済み在庫からJAN・倉庫対応を作成できません")
        return sorted(proposal, key=lambda item: (item["source_center"], item["jan"]))

    def _inventory_context(
        self, registration: dict, inventory_view: dict
    ) -> tuple[dict[str, str], dict[str, date]]:
        handoff = self.inventory_pipeline.get_handoff(registration["handoff_id"])
        locations = {item["source_center"]: item for item in handoff["locations"]}
        totals: dict[str, Decimal] = {}
        snapshot_dates: dict[str, date] = {}
        for job in inventory_view["jobs"]:
            if not job["snapshot_id"]:
                continue
            center_id = locations[job["source_center"]]["location_code"]
            snapshot = self.inventory_store.get_snapshot(job["snapshot_id"])
            if snapshot is None:
                raise FormalForecastError("承認済み在庫Snapshotが見つかりません")
            snapshot_dates[job["source_center"]] = datetime.fromisoformat(
                snapshot["snapshot_at"]
            ).date()
            for bucket in self.inventory_store.list_expiry_buckets_with_location(
                job["snapshot_id"]
            ):
                uid = f"{bucket['jan']}::{center_id}"
                totals[uid] = totals.get(uid, Decimal("0")) + Decimal(
                    str(bucket["quantity_cases"])
                )
        return ({key: str(value) for key, value in totals.items()}, snapshot_dates)

    def _latest(self, registration_id: str) -> dict | None:
        values = []
        for path in self.root.glob("portable-daily-*/manifest.json"):
            try:
                value = self._verified_result(path)
            except FormalForecastError:
                continue
            if value.get("registration_id") == registration_id:
                values.append(value)
        return (
            max(values, key=lambda item: (item["created_at"], item["build_id"]))
            if values
            else None
        )

    def _verified_result(self, manifest_path: Path) -> dict:
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            daily = manifest_path.with_name("daily.csv").read_bytes()
            predictions = manifest_path.with_name("predictions.json").read_bytes()
            parsed_predictions = json.loads(predictions)
        except (OSError, json.JSONDecodeError) as exc:
            raise FormalForecastError("予測結果の整合性を確認できません") from exc
        if (
            value.get("daily_data_sha256") != sha256(daily)
            or value.get("prediction_sha256") != sha256(predictions)
            or value.get("predictions") != parsed_predictions
        ):
            raise FormalForecastError("予測結果の整合性を確認できません")
        return value

    @staticmethod
    def _atomic_json(path: Path, value: dict) -> None:
        PortableFormalForecastPipeline._atomic_bytes(path, canonical_json(value))

    @staticmethod
    def _atomic_bytes(path: Path, value: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(value)
        os.replace(temporary, path)


def translate_error(exc: Exception) -> FormalForecastError:
    if isinstance(exc, FormalForecastError):
        return exc
    if isinstance(exc, (FormalPipelineError, FormalShipmentBuildError, OSError, KeyError)):
        return FormalForecastError(str(exc))
    raise exc


def _shipment_issue_evidence(
    report: dict,
) -> tuple[set[tuple[str, str, date]], set[tuple[str, date]]]:
    occurrences: set[tuple[str, str, date]] = set()
    files: set[tuple[str, date]] = set()
    for issue in report.get("issues", []):
        if issue.get("reason") == "SHIPMENT_ROW_INVALID":
            parts = str(issue.get("source_value") or "").split("|", 3)
            if len(parts) == 4:
                day = _business_date(parts[2])
                if day is not None:
                    occurrences.add((parts[0], parts[1], day))
        elif issue.get("reason") == "HEADER_MISSING":
            center, day = _center_and_file_date(str(issue.get("source_value") or ""))
            if day is not None:
                files.add((center, day))
    return occurrences, files
