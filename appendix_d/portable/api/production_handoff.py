"""Register a verified Portable daily build in the existing production run contracts."""

from __future__ import annotations

import csv
import io
import json
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

from forecast_provider.api.schemas import ExperimentCreate, SnapshotCreate
from forecast_provider.api.service import ApplicationService
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore

from .formal_pipeline import PortableFormalPipeline
from .formal_shipment_daily import canonical_json, sha256
from .runtime_assignments import PortableRuntimeAssignments, RuntimeAssignmentError
from .runtime_profiles import enforce_resource_limits

RUN_NAMESPACE = uuid.UUID("9c197980-397e-4a47-a3cc-8abbdc9c4299")


class ProductionHandoffError(ValueError):
    pass


class PortableProductionHandoff:
    """One-way adapter. Portable files remain evidence; production owns the run ledger."""

    def __init__(self, paths) -> None:
        self.paths = paths
        self.database = paths.state / "production-forecast.sqlite3"
        self.snapshot_root = paths.formal_forecast / "ProductionSnapshots"
        self.receipt_root = paths.formal_forecast / "ProductionHandoffs"
        self.snapshot_root.mkdir(parents=True, exist_ok=True)
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.service = ApplicationService(
            SqliteRunStore(self.database),
            SqliteCatalogStore(self.database),
            self.snapshot_root,
        )
        self.runtime_assignments = PortableRuntimeAssignments(paths)

    def view(self, build_id: str) -> dict:
        manifest, _ = self._verified_source(build_id)
        receipt = self._receipt_path(build_id)
        handoff = None if not receipt.is_file() else self._verified_receipt(receipt)
        if handoff is not None:
            handoff = self._run_view(handoff)
        return {
            "build_id": build_id,
            "source_status": manifest["status"],
            "eligible_series_count": manifest["eligible_series_count"],
            "blocked_series_count": manifest["blocked_series_count"],
            "queued": receipt.is_file(),
            "handoff": handoff,
        }

    def enqueue(self, build_id: str, payload: dict) -> dict:
        actor = str(payload.get("actor") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        if not actor or not reason:
            raise ProductionHandoffError("登録者と登録理由を入力してください")
        if payload.get("confirm_production_queue") is not True:
            raise ProductionHandoffError("Production Forecast Runへの登録確認が必要です")
        manifest, daily = self._verified_source(build_id)
        if manifest["eligible_series_count"] < 1:
            raise ProductionHandoffError("予測可能な系列がありません")
        receipt_path = self._receipt_path(build_id)
        if receipt_path.is_file():
            return self._verified_receipt(receipt_path)

        try:
            runtime_resolutions = self.runtime_assignments.resolve_execution(
                build_id, self._pilot_scope_versions(manifest), actor,
            )
        except RuntimeAssignmentError as exc:
            raise ProductionHandoffError(str(exc)) from exc
        blocked = [item for item in runtime_resolutions if item["status"] == "BLOCKED"]
        if blocked:
            reasons = "、".join(sorted({item["reason_code"] for item in blocked}))
            raise ProductionHandoffError(f"実行時の候補版選択を確認できません: {reasons}")
        runtime_hashes = {
            item["selected_configuration_sha256"] for item in runtime_resolutions
        }
        if len(runtime_hashes) != 1:
            raise ProductionHandoffError("実行時設定を単一の予測Runへ固定できません")
        runtime_configuration = runtime_resolutions[0]["selected_configuration"]

        eligible = {
            item["unique_id"] for item in manifest["series"] if item["forecast_eligible"]
        }
        if any(item["status"] == "CANDIDATE_SELECTED" for item in runtime_resolutions):
            try:
                train_start = date.fromisoformat(manifest["train_start"])
                train_end_for_limit = date.fromisoformat(manifest["train_end"])
                enforce_resource_limits(
                    runtime_configuration,
                    series=len(eligible),
                    history_days=(train_end_for_limit - train_start).days + 1,
                    horizon_days=int(manifest["horizon_days"]),
                )
            except ValueError as exc:
                raise ProductionHandoffError(str(exc)) from exc
        snapshot_bytes = _production_csv(daily, eligible)
        snapshot_sha = sha256(snapshot_bytes)
        snapshot_path = self.snapshot_root / f"{snapshot_sha}.csv"
        _atomic_bytes(snapshot_path, snapshot_bytes)

        train_end = date.fromisoformat(manifest["train_end"])
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=int(manifest["horizon_days"]) - 1)
        snapshot = self.service.create_snapshot(
            SnapshotCreate(
                data_uri=snapshot_path.resolve().as_uri(),
                data_sha256=snapshot_sha,
                selection_version=manifest["identity_bridge_version"],
                unique_ids=tuple(sorted(eligible)),
                train_start=date.fromisoformat(manifest["train_start"]),
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                origin_interval_days=int(manifest["horizon_days"]),
                max_horizon=int(manifest["horizon_days"]),
                primary_horizon_max=int(manifest["horizon_days"]),
                report_horizons=(7, int(manifest["horizon_days"])),
                availability_mode="ASSUMED",
            )
        )
        experiment = self.service.create_experiment(
            ExperimentCreate(
                snapshot_id=snapshot.snapshot_id,
                provider_id=runtime_configuration["provider_id"],
                model_name=runtime_configuration["model_name"],
                params=runtime_configuration["params"],
                preprocessing_version=runtime_configuration["preprocessing_version"],
                seed=runtime_configuration["seed"],
                resource_profile=runtime_configuration["resource_profile"],
            )
        )
        run_id = str(uuid.uuid5(RUN_NAMESPACE, build_id))
        run = self.service.ensure_run(experiment.experiment_id, run_id)
        receipt = {
            "format": "portable-production-handoff-v1",
            "build_id": build_id,
            "source_manifest_sha256": sha256(canonical_json(manifest)),
            "source_daily_sha256": manifest["daily_data_sha256"],
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_data_sha256": snapshot_sha,
            "experiment_id": experiment.experiment_id,
            "run_id": run.run_id,
            "run_status": run.status,
            "provider_id": runtime_configuration["provider_id"],
            "model_name": runtime_configuration["model_name"],
            "runtime_version": runtime_configuration["version"],
            "runtime_configuration_sha256": next(iter(runtime_hashes)),
            "runtime_resolutions": runtime_resolutions,
            "actor": actor,
            "reason": reason,
            "eligible_series": sorted(eligible),
            "blocked_series": sorted(
                item["unique_id"]
                for item in manifest["series"]
                if not item["forecast_eligible"]
            ),
        }
        receipt["receipt_sha256"] = sha256(canonical_json(receipt))
        _atomic_bytes(receipt_path, canonical_json(receipt))
        return receipt

    def _pilot_scope_versions(self, manifest: dict) -> list[str]:
        pipeline = PortableFormalPipeline(self.paths)
        registration = pipeline.get_registration(manifest["registration_id"])
        result = []
        for item in registration["jobs"]:
            job = pipeline.inventory_store.get_job(item["job_id"])
            if job is None or not job.pilot_scope_version:
                raise ProductionHandoffError("Production RunのPilot Scopeを確認できません")
            result.append(job.pilot_scope_version)
        return result

    def run_id(self, build_id: str) -> str:
        receipt = self._receipt_path(build_id)
        if not receipt.is_file():
            raise ProductionHandoffError("Production Forecast Runが登録されていません")
        return str(self._verified_receipt(receipt)["run_id"])

    def _run_view(self, receipt: dict) -> dict:
        run = self.service.runs.get_run(receipt["run_id"])
        if run is None:
            raise ProductionHandoffError("Production Forecast Runが見つかりません")
        output = {**receipt, "run_status": run.status, "origin_counts": run.origin_counts}
        if run.status == "SUCCEEDED":
            result = self.service.runs.get_run_results(run.run_id) or {}
            points = [
                item for item in result.get("values", [])
                if item["forecast_kind"] == "POINT" and item["quantile"] is None
            ]
            output["point_predictions"] = points
        return output

    def _verified_source(self, build_id: str) -> tuple[dict, bytes]:
        if not build_id.startswith("portable-daily-") or len(build_id) != 79:
            raise ProductionHandoffError("日次buildが見つかりません")
        root = self.paths.formal_forecast / build_id
        try:
            manifest_bytes = (root / "manifest.json").read_bytes()
            daily = (root / "daily.csv").read_bytes()
            manifest = json.loads(manifest_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionHandoffError("日次buildが見つかりません") from exc
        if (
            manifest.get("build_id") != build_id
            or manifest.get("daily_data_sha256") != sha256(daily)
            or manifest.get("status")
            not in {"FORECAST_COMPLETED", "FORECAST_COMPLETED_WITH_BLOCKERS"}
        ):
            raise ProductionHandoffError("日次buildの整合性を確認できません")
        return manifest, daily

    def _receipt_path(self, build_id: str) -> Path:
        return self.receipt_root / f"{build_id}.json"

    @staticmethod
    def _verified_receipt(path: Path) -> dict:
        try:
            value = json.loads(path.read_bytes())
            expected = value.pop("receipt_sha256")
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProductionHandoffError("受渡し記録の整合性を確認できません") from exc
        actual = sha256(canonical_json(value))
        value["receipt_sha256"] = expected
        if actual != expected:
            raise ProductionHandoffError("受渡し記録の整合性を確認できません")
        return value


def _production_csv(raw: bytes, eligible: set[str]) -> bytes:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        required = {
            "unique_id", "canonical_product_id", "center_id", "ds", "y",
            "state", "raw_quantity", "issue",
        }
        if not required.issubset(reader.fieldnames or ()):
            raise ProductionHandoffError("日次CSVの列が一致しません")
        rows = [row for row in reader if row["unique_id"] in eligible]
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ProductionHandoffError("日次CSVを読み込めません") from exc
    if {row["unique_id"] for row in rows} != eligible:
        raise ProductionHandoffError("予測対象系列の日次データが不足しています")
    target = io.StringIO(newline="")
    fields = (
        "unique_id", "canonical_product_id", "center_id", "ds", "y",
        "daily_state", "raw_quantity", "issue",
    )
    writer = csv.DictWriter(target, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in sorted(rows, key=lambda item: (item["unique_id"], item["ds"])):
        writer.writerow({
            "unique_id": row["unique_id"], "canonical_product_id": row["canonical_product_id"],
            "center_id": row["center_id"], "ds": row["ds"], "y": row["y"],
            "daily_state": row["state"], "raw_quantity": row["raw_quantity"],
            "issue": row["issue"],
        })
    return target.getvalue().encode("utf-8")


def _atomic_bytes(path: Path, value: bytes) -> None:
    if path.is_file():
        if path.read_bytes() != value:
            raise ProductionHandoffError("同じIDの保存内容が一致しません")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)
