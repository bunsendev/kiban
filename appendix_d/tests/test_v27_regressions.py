"""v2.7で固定する追加契約。v2.6レビューで再現した穴を回帰テスト化する。"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from test_builtin_baseline import (
    TRAIN_END,
    make_context,
    make_dataset,
    make_future,
    make_valid_predict_frame,
)
from test_v26_regressions import fixture_comparison

from forecast_provider import (
    ModelMetadata,
    ProviderConfig,
    ProviderRegistry,
    registry,
)
from forecast_provider.errors import ContractViolationError, NonRetryableProviderError
from forecast_provider.evaluation import build_plan, compare_runs, reconcile_predictions
from forecast_provider.providers.builtin_baseline import BuiltinBaselineProvider
from forecast_provider.runner import available_history


def _training_data(days: int = 731) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "unique_id": "A",
            "ds": pd.date_range(end=TRAIN_END, periods=days),
            "y": np.arange(days, dtype=float),
        }
    )


def test_run_success_rate_does_not_hide_failure_on_missing_truth() -> None:
    ds, _, out, _, truth = fixture_comparison()
    failed_key = out.iloc[0][["unique_id", "origin_date", "target_date", "horizon"]]
    damaged = out.drop(index=out.index[0]).reset_index(drop=True)
    truth.loc[
        (truth.unique_id == failed_key.unique_id) & (truth.ds == failed_key.target_date), "y"
    ] = np.nan

    result = compare_runs({"run": ds}, {"run": damaged}, truth, truth_version="v1")
    score = result["scores"]["run"]

    assert score["run_failure_count"] == 1
    assert score["run_success_rate"] < 1.0
    assert score["truth_missing_count"] == 1
    assert not score["official_eligible"]
    assert not result["ranking_ready"]


def test_different_schedule_cannot_turn_run_failures_into_100_percent() -> None:
    a, b, out_a, out_b, truth = fixture_comparison()
    key = ["unique_id", "origin_date", "target_date", "horizon"]
    shared = build_plan(a).merge(build_plan(b), on=key)
    shared_h7 = shared[shared.horizon.eq(7)]
    damaged_b = out_b.merge(
        shared_h7,
        on=["unique_id", "origin_date", "target_date", "horizon"],
        how="inner",
    )
    result = compare_runs(
        {"a": a, "b": b},
        {"a": out_a, "b": damaged_b},
        truth,
        truth_version="v1",
        horizon=7,
    )
    score = result["scores"]["b"]
    assert score["shared_success_count"] == score["shared_planned_count"]
    assert score["run_failure_count"] > 0
    assert score["run_success_rate"] < 1.0
    assert not result["ranking_ready"]


def test_future_frame_is_allow_listed_by_dataset_known_future_columns() -> None:
    provider = registry.create("builtin-baseline")
    context = make_context()
    dataset = replace(make_dataset(("A",)), known_future_columns=("promo",))
    config = ProviderConfig(
        "builtin-baseline", "seasonal_naive_7", preprocessing_version="daily-nan-preserving-v1"
    )
    data = _training_data()
    model = provider.fit_parameters(data, dataset, config, context)
    state = provider.refresh_context(
        model, data, TRAIN_END.date(), context.for_origin(TRAIN_END.date())
    )

    allowed = make_future(["A"], TRAIN_END, [1])
    allowed["promo"] = 1.0
    assert not provider.predict(
        model, state, allowed, [1], context.for_origin(state.origin_date)
    ).empty

    forbidden = allowed.copy()
    forbidden["observed_future_sales"] = 999999.0
    with pytest.raises(ContractViolationError, match="未許可列"):
        provider.predict(model, state, forbidden, [1], context.for_origin(state.origin_date))


def test_observed_keeps_late_date_as_nan_and_requires_arrival_evidence() -> None:
    data = pd.DataFrame(
        {
            "unique_id": ["A", "A"],
            "ds": pd.to_datetime(["2025-12-30", "2025-12-31"]),
            "y": [1.0, 2.0],
            "available_at": pd.to_datetime(["2025-12-31T00:00+09:00", "2026-01-01T09:00+09:00"]),
        }
    )
    history = available_history(data, TRAIN_END, availability_mode="OBSERVED")
    assert history.ds.tolist() == [pd.Timestamp("2025-12-30"), pd.Timestamp("2025-12-31")]
    assert history.y.iloc[0] == 1.0
    assert pd.isna(history.y.iloc[1])
    assert "available_at" in history

    provider = BuiltinBaselineProvider()
    dataset = replace(make_dataset(("A",)), availability_mode="OBSERVED")
    config = ProviderConfig(
        "builtin-baseline",
        "seasonal_naive_7",
        preprocessing_version="daily-nan-preserving-v1",
        interval_levels=(0.8,),
    )
    check = provider.validate(dataset, config)
    assert check.ok
    with pytest.raises(ContractViolationError, match="available_at"):
        provider.fit_parameters(
            _training_data(),
            dataset,
            config,
            replace(make_context(), availability_mode="OBSERVED"),
        )


def test_dataset_and_provider_config_are_immune_to_external_mutation() -> None:
    ids = ["A"]
    known = ["promo"]
    dataset = replace(make_dataset(("A",)), unique_ids=ids, known_future_columns=known)
    ids.append("B")
    known.append("future_sales")
    assert dataset.unique_ids == ("A",)
    assert dataset.known_future_columns == ("promo",)

    raw = {"nested": {"window": [1, 2]}}
    config = ProviderConfig("x", "m", preprocessing_version="daily-nan-preserving-v1", params=raw)
    raw["nested"]["window"].append(3)
    assert config.params["nested"]["window"] == (1, 2)
    with pytest.raises(TypeError):
        config.params["x"] = 1


def test_builtin_baseline_rejects_unknown_params() -> None:
    provider = registry.create("builtin-baseline")
    dataset = make_dataset(("A",))
    config = ProviderConfig(
        "builtin-baseline",
        "seasonal_naive_7",
        preprocessing_version="daily-nan-preserving-v1",
        params={"lag": 999},
    )
    check = provider.validate(dataset, config)
    assert not check.ok
    assert any(issue.code == "BASELINE_UNKNOWN_PARAMS" for issue in check.issues)
    with pytest.raises(ContractViolationError, match="params"):
        provider.fit_parameters(_training_data(), dataset, config, make_context())


def test_partial_quantiles_are_contract_violation_not_unavailable() -> None:
    result = make_valid_predict_frame()
    result = result[result["quantile"].isna() | result["quantile"].eq(0.1)].copy()
    plan = result[["unique_id", "origin_date", "target_date", "horizon"]].drop_duplicates()
    with pytest.raises(ContractViolationError, match="一部"):
        reconcile_predictions(plan, result, expected_quantiles={0.1, 0.5, 0.9})


def test_registry_rejects_key_metadata_id_mismatch() -> None:
    class WrongIdProvider(BuiltinBaselineProvider):
        def metadata(self):
            return replace(super().metadata(), provider_id="metadata-id")

    local = ProviderRegistry()
    with pytest.raises(NonRetryableProviderError, match="一致しません"):
        local.register("registry-id", WrongIdProvider)


def test_metadata_integer_contracts_reject_bool_and_float() -> None:
    with pytest.raises(ValueError):
        ModelMetadata("m", "M", True, (1, 10), True)
    with pytest.raises(ValueError):
        ModelMetadata("m", "M", 7, (1.5, 10), True)
    with pytest.raises(ValueError):
        ModelMetadata("m", "M", 7, (1, True), True)


def test_dataset_ids_and_known_future_column_definitions_are_strict() -> None:
    with pytest.raises(ValueError):
        replace(make_dataset(("A",)), dataset_snapshot_id="")
    with pytest.raises(ValueError):
        replace(make_dataset(("A",)), selection_version="")
    with pytest.raises(ValueError):
        replace(make_dataset(("A",)), known_future_columns=("promo", "promo"))
    with pytest.raises(ValueError):
        replace(make_dataset(("A",)), known_future_columns=("y",))
    with pytest.raises(ValueError):
        replace(make_dataset(("A",)), known_future_columns=("",))
