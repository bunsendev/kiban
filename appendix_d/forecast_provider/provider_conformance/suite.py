"""人工データだけでForecastProvider固定7項目を実行する適合試験。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from ..catalog.domain import config_from_definition
from ..contracts import ForecastDataset
from ..errors import ContractViolationError
from ..evaluation import build_plan
from ..frames import quantiles_from_interval_levels, validate_predict_frame
from ..run_context import RunContext, cutoff_for_origin

SUITE_VERSION = "provider-contract-v2"


@dataclass(frozen=True)
class SuiteResult:
    checks: list[dict]
    evidence: dict


def run_suite(provider, definition: dict, availability_mode: str, work_dir: Path) -> SuiteResult:
    """実験と同じadapter設定を、外部データを使わず検証する。"""
    metadata = provider.metadata()
    model_metadata = metadata.get_model(definition["model_name"])
    if model_metadata is None:
        raise ValueError("実験のmodelがProviderメタデータにありません")
    horizon = min(15, model_metadata.supported_horizons[1])
    history_days = max(420, model_metadata.min_history_days + 35)
    dataset = _dataset(history_days, horizon, availability_mode)
    config = config_from_definition(definition)
    validation = provider.validate(dataset, config)
    if not validation.ok:
        messages = [item.message for item in validation.issues if item.blocking]
        raise ValueError("人工データ試験の設定が不正です: " + "; ".join(messages))
    frame = _artificial_frame(dataset)
    context = _context(definition, dataset.train_end, availability_mode, work_dir)
    train = frame[frame.ds.le(pd.Timestamp(dataset.train_end))].copy()
    model = provider.fit_parameters(train, dataset, config, context)
    future = build_plan(dataset)
    future = future[future.origin_date.eq(pd.Timestamp(dataset.train_end))].copy()
    history = train.copy()
    ref = provider.refresh_context(model, history, dataset.train_end, context)
    horizons = sorted(future.horizon.unique().tolist())
    predicted = provider.predict(model, ref, future, horizons, context)

    checks = [
        _check(
            "TRAIN_BOUNDARY",
            lambda: _train_boundary(provider, frame, dataset, config, context),
        ),
        _check(
            "PARAMETER_IMMUTABILITY",
            lambda: _immutability(model, provider, ref, future, horizons, context),
        ),
        _check(
            "CONTEXT_REFRESH",
            lambda: _context_refresh(
                provider, model, frame, dataset, work_dir, definition
            ),
        ),
        _check(
            "FUTURE_NON_REFERENCE",
            lambda: _future_non_reference(
                provider, model, ref, future, horizons, context
            ),
        ),
        _check("OUTPUT_COMPLETENESS", lambda: _output_complete(predicted, future, config)),
        _check(
            "REPRODUCIBILITY",
            lambda: _reproducible(
                provider, model, ref, future, horizons, context, predicted
            ),
        ),
        _check(
            "FAILURE_NOTIFICATION",
            lambda: _failure_notification(provider, model, ref, future, context),
        ),
    ]
    evidence = {
        "schema_version": 1,
        "suite_version": SUITE_VERSION,
        "synthetic_dataset": {
            "series_count": 2,
            "history_days": history_days,
            "max_horizon": horizon,
            "availability_mode": availability_mode,
        },
        "provider": {
            "provider_id": metadata.provider_id,
            "provider_version": metadata.provider_version,
            "model_id": definition["model_name"],
            "library_name": metadata.library_name,
            "library_version": metadata.library_version,
        },
        "adapter_config": {
            "params": definition.get("params", {}),
            "interval_levels": definition.get("interval_levels", []),
            "preprocessing_version": definition["preprocessing_version"],
        },
        "checks": checks,
    }
    return SuiteResult(checks, evidence)


def _dataset(history_days: int, horizon: int, availability_mode: str) -> ForecastDataset:
    train_start = date(2024, 1, 1)
    train_end = train_start + timedelta(days=history_days - 1)
    return ForecastDataset(
        "synthetic-provider-conformance-v2",
        "synthetic-v1",
        ("synthetic-a", "synthetic-b"),
        train_start,
        train_end,
        train_end + timedelta(days=1),
        train_end + timedelta(days=horizon),
        horizon,
        horizon,
        horizon,
        tuple(sorted({1, min(7, horizon), horizon})),
        (),
        availability_mode,
    )


def _artificial_frame(dataset: ForecastDataset) -> pd.DataFrame:
    days = pd.date_range(dataset.train_start, dataset.test_end)
    rows = []
    for index, uid in enumerate(dataset.unique_ids):
        for offset, day in enumerate(days):
            value = 25 + index * 5 + offset * 0.02 + 4 * np.sin(2 * np.pi * offset / 7)
            rows.append({"unique_id": uid, "ds": day, "y": max(0.0, float(value))})
    frame = pd.DataFrame(rows)
    if dataset.availability_mode == "OBSERVED":
        frame["available_at"] = (
            frame["ds"].dt.tz_localize("Asia/Tokyo") + pd.Timedelta(days=1)
        ).dt.tz_convert("UTC")
    return frame


def _context(definition, origin: date, mode: str, work_dir: Path) -> RunContext:
    work_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(
        "provider-conformance",
        "synthetic-experiment",
        int(definition["seed"]),
        datetime.now(UTC) + timedelta(hours=6),
        work_dir,
        work_dir,
        definition["resource_profile"],
        logging.getLogger("provider-conformance"),
        availability_mode=mode,
        cutoff_at=cutoff_for_origin(origin),
        origin_date=origin,
    )


def _check(code: str, execute) -> dict:
    try:
        evidence = execute()
    except Exception as exc:
        return {
            "code": code,
            "status": "FAILED",
            "evidence": f"{type(exc).__name__}: {str(exc)[:240]}",
        }
    return {"code": code, "status": "PASSED", "evidence": evidence}


def _expect_contract_error(callable_value, evidence: str) -> str:
    try:
        callable_value()
    except ContractViolationError:
        return evidence
    raise AssertionError("契約違反が通知されませんでした")


def _train_boundary(provider, frame, dataset, config, context) -> str:
    invalid = frame[frame.ds.le(pd.Timestamp(dataset.train_end + timedelta(days=1)))].copy()
    return _expect_contract_error(
        lambda: provider.fit_parameters(invalid, dataset, config, context),
        "TRAIN終了翌日の実績を学習入力として拒否",
    )


def _immutability(model, provider, ref, future, horizons, context) -> str:
    before = model.parameter_fingerprint
    provider.predict(model, ref, future, horizons, context)
    if model.parameter_fingerprint != before:
        raise AssertionError("予測処理でparameter fingerprintが変化しました")
    return f"学習済みparameter fingerprintを維持: {before}"


def _context_refresh(provider, model, frame, dataset, work_dir, definition) -> str:
    later = dataset.train_end + timedelta(days=1)
    context = _context(definition, later, dataset.availability_mode, work_dir)
    history = frame[frame.ds.le(pd.Timestamp(later))].copy()
    ref = provider.refresh_context(model, history, later, context)
    if ref.origin_date != later or ref.history_end != later:
        raise AssertionError("起点時点まで履歴が更新されませんでした")
    return f"履歴コンテキストを{later.isoformat()}まで更新"


def _future_non_reference(provider, model, ref, future, horizons, context) -> str:
    invalid = future.copy()
    invalid["y"] = 999999.0
    return _expect_contract_error(
        lambda: provider.predict(model, ref, invalid, horizons, context),
        "予測対象に混入した未来実績yを拒否",
    )


def _output_complete(predicted, future, config) -> str:
    validate_predict_frame(
        predicted,
        expected_targets=future,
        expected_quantiles=set(quantiles_from_interval_levels(config.interval_levels)),
    )
    return f"{len(future)}対象、{len(predicted)}予測行の必須列・キー・値を検証"


def _reproducible(provider, model, ref, future, horizons, context, first) -> str:
    second = provider.predict(model, ref, future, horizons, context)
    assert_frame_equal(
        first.reset_index(drop=True), second.reset_index(drop=True), check_exact=True
    )
    return "同一入力の2回実行が完全一致"


def _failure_notification(provider, model, ref, future, context) -> str:
    return _expect_contract_error(
        lambda: provider.predict(model, ref, future, [0], context),
        "不正horizonをContractViolationErrorで通知",
    )
