"""Issue immutable, smoke-tested runtime candidate packages."""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from forecast_provider import ForecastDataset, ProviderConfig, RunContext, registry
from forecast_provider.frames import validate_predict_frame
from forecast_provider.run_context import cutoff_for_origin

from .formal_changes import PortableFormalChanges
from .formal_shipment_daily import canonical_json, sha256
from .production_handoff import ProductionHandoffError
from .runtime_profiles import (
    ADAPTER,
    BASELINE_CONFIGURATION,
    RESOURCE_LIMITS,
    SUPPORTED_BASELINE_MODELS,
    supported_configuration,
)

MANIFEST_FORMAT = "bunsen-portable-runtime-candidate-v2"
RECEIPT_FORMAT = "bunsen-portable-runtime-package-receipt-v1"


class PortableCandidatePackages:
    def __init__(self, paths) -> None:
        self.paths = paths
        self.database = paths.state / "shipment-actual-outcomes.sqlite3"
        self.formal_changes = PortableFormalChanges(self.database)
        self.manifest_root = paths.state / "RuntimeCandidates"
        self.receipt_root = paths.state / "RuntimeCandidatePackages"
        self.manifest_root.mkdir(parents=True, exist_ok=True)
        self.receipt_root.mkdir(parents=True, exist_ok=True)

    def overview(self) -> dict:
        eligible = []
        formal = self.formal_changes.overview()
        for summary in formal["proposals"]:
            proposal = self.formal_changes.view_proposal(summary["proposal_id"])
            if (
                proposal["status"] == "APPROVED_FOR_IMPLEMENTATION"
                and proposal["change_target"] == "FORECAST_MODEL"
            ):
                eligible.append({
                    "proposal_id": proposal["proposal_id"],
                    "candidate_version": proposal["proposed_configuration"].get("version"),
                    "model_name": proposal["proposed_configuration"].get("model_name"),
                    "supported": supported_configuration(
                        proposal["proposed_configuration"]
                    ),
                    "decision_revision": proposal["revision"],
                })
        packages = [self._verified_receipt(path) for path in sorted(
            self.receipt_root.glob("*.json"), reverse=True
        )]
        return {
            "mode": "SHADOW",
            "eligible_proposals": eligible,
            "packages": packages[:200],
            "supported_models": sorted(SUPPORTED_BASELINE_MODELS),
            "resource_limits": RESOURCE_LIMITS,
            "notice": (
                "承認済み変更案の固定設定だけを人工データで起動確認し、"
                "Pilot Scope用の候補版manifestとして発行します。"
            ),
        }

    def issue(self, payload: dict) -> dict:
        proposal_id = _text(payload.get("proposal_id"), "正式変更案", 200)
        actor = _text(payload.get("actor"), "発行担当者", 100)
        known_at = _datetime(payload.get("known_at"), "発行基準日時")
        if payload.get("confirm_shadow_package") is not True:
            raise ProductionHandoffError(
                "Pilot Scope限定のSHADOW候補版であることを確認してください"
            )
        if payload.get("confirm_rollback_target") is not True:
            raise ProductionHandoffError("固定されたrollback先版を確認してください")
        proposal = self.formal_changes.view_proposal(proposal_id)
        if proposal["status"] != "APPROVED_FOR_IMPLEMENTATION":
            raise ProductionHandoffError("現在も承認済みの正式変更案だけを発行できます")
        if proposal["change_target"] != "FORECAST_MODEL":
            raise ProductionHandoffError("予測モデルの変更案だけを候補版として発行できます")
        configuration = proposal["proposed_configuration"]
        if not supported_configuration(configuration):
            raise ProductionHandoffError("Portable Workerが対応していない候補設定です")
        if configuration["version"] == proposal["rollback_target_version"]:
            raise ProductionHandoffError("候補版とrollback先版は別の版にしてください")
        if known_at < datetime.fromisoformat(proposal["decision_history"][-1]["known_at"]):
            raise ProductionHandoffError("発行基準日時は変更案の承認日時以降です")

        smoke = _run_smoke(configuration, self.paths.state)
        body = {
            "format": MANIFEST_FORMAT,
            "candidate_version": configuration["version"],
            "proposal_id": proposal_id,
            "source_proposal_decision_revision": proposal["revision"],
            "runtime_configuration": configuration,
            "runtime_configuration_sha256": sha256(canonical_json(configuration)),
            "adapter": ADAPTER,
            "resource_limits": RESOURCE_LIMITS,
            "rollback": {
                "target_version": proposal["rollback_target_version"],
                "baseline_configuration_sha256": sha256(
                    canonical_json(BASELINE_CONFIGURATION)
                ),
            },
            "smoke_test": smoke,
            "issued_by": actor,
            "known_at": known_at.astimezone(UTC).isoformat(),
        }
        package_id = f"runtime-candidate-{sha256(canonical_json(body))}"
        manifest = {**body, "package_id": package_id}
        raw = canonical_json(manifest)
        manifest_sha = sha256(raw)
        manifest_path = self.manifest_root / f"{_safe_version(configuration['version'])}.json"
        _atomic(manifest_path, raw)
        receipt_body = {
            "format": RECEIPT_FORMAT,
            "package_id": package_id,
            "proposal_id": proposal_id,
            "source_proposal_decision_revision": proposal["revision"],
            "candidate_version": configuration["version"],
            "model_name": configuration["model_name"],
            "manifest_sha256": manifest_sha,
            "manifest_path": f"RuntimeCandidates/{manifest_path.name}",
            "resource_limits": RESOURCE_LIMITS,
            "rollback_target_version": proposal["rollback_target_version"],
            "smoke_test": smoke,
            "actor": actor,
            "known_at": known_at.astimezone(UTC).isoformat(),
        }
        receipt = {**receipt_body, "content_sha256": sha256(canonical_json(receipt_body))}
        _atomic(self.receipt_root / f"{package_id}.json", canonical_json(receipt))
        return receipt

    def _verified_receipt(self, path: Path) -> dict:
        try:
            value = json.loads(path.read_bytes())
            expected = value.pop("content_sha256")
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ProductionHandoffError("候補版発行記録の整合性を確認できません") from exc
        if (
            value.get("format") != RECEIPT_FORMAT
            or sha256(canonical_json(value)) != expected
        ):
            raise ProductionHandoffError("候補版発行記録の整合性を確認できません")
        manifest = self.manifest_root / Path(value["manifest_path"]).name
        if not manifest.is_file() or sha256(manifest.read_bytes()) != value["manifest_sha256"]:
            raise ProductionHandoffError("発行済み候補manifestの整合性を確認できません")
        return {**value, "content_sha256": expected}


def _run_smoke(configuration: dict, work_parent: Path) -> dict:
    model = configuration["model_name"]
    origin = date(2026, 1, 31)
    start = origin - timedelta(days=399)
    rows = [
        {"unique_id": uid, "ds": pd.Timestamp(start + timedelta(days=offset)),
         "y": float(10 + uid_index * 5 + (offset % 7))}
        for uid_index, uid in enumerate(("smoke-a", "smoke-b"))
        for offset in range(400)
    ]
    frame = pd.DataFrame(rows)
    dataset = ForecastDataset(
        dataset_snapshot_id="portable-candidate-smoke-v1",
        selection_version="portable-candidate-smoke-v1",
        unique_ids=("smoke-a", "smoke-b"), train_start=start, train_end=origin,
        test_start=origin + timedelta(days=1), test_end=origin + timedelta(days=7),
        origin_interval_days=7, max_horizon=7, primary_horizon_max=7,
        report_horizons=(7,), availability_mode="ASSUMED",
    )
    config = ProviderConfig(
        provider_id="builtin-baseline", model=model,
        preprocessing_version=configuration["preprocessing_version"], interval_levels=(),
    )
    provider = registry.create("builtin-baseline")
    validation = provider.validate(dataset, config)
    if not validation.ok:
        raise ProductionHandoffError("候補版smoke testの入力検証に失敗しました")
    with tempfile.TemporaryDirectory(prefix="candidate-smoke-", dir=work_parent) as tmp:
        work = Path(tmp)
        context = RunContext(
            run_id=f"smoke-{uuid.uuid4().hex}", experiment_id="candidate-package-smoke",
            seed=configuration["seed"], deadline=datetime.now(UTC) + timedelta(seconds=30),
            input_dir=work, output_dir=work,
            resource_profile=configuration["resource_profile"],
            logger=logging.getLogger("portable.candidate.smoke"),
            availability_mode="ASSUMED", cutoff_at=cutoff_for_origin(origin),
            origin_date=origin,
        )
        model_ref = provider.fit_parameters(frame, dataset, config, context)
        context_ref = provider.refresh_context(model_ref, frame, origin, context)
        future = pd.DataFrame([
            {"unique_id": uid, "origin_date": pd.Timestamp(origin),
             "target_date": pd.Timestamp(origin + timedelta(days=horizon)),
             "horizon": horizon}
            for uid in dataset.unique_ids for horizon in range(1, 8)
        ])
        predicted = provider.predict(
            model_ref, context_ref, future, list(range(1, 8)), context
        )
        validate_predict_frame(predicted, expected_targets=future)
    points = predicted[
        (predicted["forecast_kind"] == "POINT") & predicted["quantile"].isna()
    ].sort_values(["unique_id", "target_date"], kind="stable")
    values = [
        {"unique_id": row.unique_id, "target_date": row.target_date.date().isoformat(),
         "horizon": int(row.horizon), "yhat": float(row.yhat)}
        for row in points.itertuples(index=False)
    ]
    if len(values) != 14 or any(not math.isfinite(item["yhat"]) for item in values):
        raise ProductionHandoffError("候補版smoke testの予測結果が不正です")
    return {
        "status": "PASSED",
        "dataset_version": "portable-candidate-smoke-v1",
        "series_count": 2,
        "forecast_count": len(values),
        "prediction_sha256": sha256(canonical_json(values)),
    }


def _atomic(path: Path, raw: bytes) -> None:
    if path.is_file():
        if path.read_bytes() != raw:
            raise ProductionHandoffError("同じ候補版の発行済み内容と一致しません")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def _safe_version(value: str) -> str:
    if not value or len(value) > 100 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in value
    ):
        raise ProductionHandoffError("候補版は英数字、ピリオド、ハイフン、下線で指定してください")
    return value


def _text(value, label: str, maximum: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise ProductionHandoffError(f"{label}は1〜{maximum}文字です")
    return result


def _datetime(value, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ProductionHandoffError(f"{label}はtimezone付きISO日時です") from exc
    if result.tzinfo is None:
        raise ProductionHandoffError(f"{label}はtimezone付きISO日時です")
    return result.astimezone(UTC)
