"""条件識別の決定性・正規化・感度と学習済み状態の不変性。"""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from forecast_provider.fingerprint import parameter_fingerprint
from forecast_provider.providers.builtin_baseline import BuiltinBaselineProvider


def fingerprint(case, **changes):
    _, dataset, config, context = case
    args = {
        "config": config,
        "dataset": dataset,
        "context": context,
        "metadata": BuiltinBaselineProvider().metadata(),
        "weights_id": None,
    }
    args.update(changes)
    return parameter_fingerprint(**args)


def test_fingerprint_ignores_order_and_run_identity(phase1a_case):
    _, dataset, config, context = phase1a_case
    left = replace(
        config,
        params={"x": [np.int64(2), {"b", "a"}], "a": {"n": 1.5}},
        interval_levels=(0.8, 0.95),
    )
    right = replace(
        config,
        params={"a": {"n": np.float64(1.5)}, "x": (2, {"a", "b"})},
        interval_levels=(0.95, 0.8),
    )
    before = fingerprint(phase1a_case, config=left)
    after = fingerprint(
        phase1a_case,
        config=right,
        dataset=replace(dataset, unique_ids=tuple(reversed(dataset.unique_ids))),
        context=replace(
            context,
            run_id="other",
            experiment_id="other",
            deadline=context.deadline + timedelta(hours=1),
        ),
    )
    assert before == after
    assert len(before) == 64


@pytest.mark.parametrize(
    "field,value",
    [
        ("params", {"window": 3}),
        ("preprocessing_version", "preprocess-v2"),
        ("interval_levels", (0.8,)),
        ("model", "seasonal_naive_7"),
    ],
)
def test_config_changes_fingerprint(phase1a_case, field, value):
    assert fingerprint(phase1a_case) != fingerprint(
        phase1a_case, config=replace(phase1a_case[2], **{field: value})
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_snapshot_id", "snapshot2"),
        ("selection_version", "selection2"),
        ("train_start", datetime(2024, 1, 2).date()),
        ("unique_ids", ("A",)),
        ("max_horizon", 20),
        ("known_future_columns", ("calendar_month",)),
    ],
)
def test_dataset_changes_fingerprint(phase1a_case, field, value):
    assert fingerprint(phase1a_case) != fingerprint(
        phase1a_case, dataset=replace(phase1a_case[1], **{field: value})
    )


def test_train_end_availability_seed_and_weights_change_fingerprint(phase1a_case):
    _, ds, _, ctx = phase1a_case
    before = fingerprint(phase1a_case)
    shifted = replace(ds, train_end=ds.train_end - timedelta(days=1), test_start=ds.train_end)
    assert before != fingerprint(
        phase1a_case, dataset=shifted, context=ctx.for_origin(shifted.train_end)
    )
    assert before != fingerprint(
        phase1a_case,
        dataset=replace(ds, availability_mode="OBSERVED"),
        context=replace(ctx, availability_mode="OBSERVED"),
    )
    assert before != fingerprint(phase1a_case, context=replace(ctx, seed=43))
    assert before != fingerprint(phase1a_case, weights_id="sha256:" + "a" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_version", "2.9.1"),
        ("library_version", "other"),
        ("runtime_dependencies", (("pandas", "other"),)),
        ("container_digest", "sha256:abc"),
    ],
)
def test_provider_environment_changes_fingerprint(phase1a_case, field, value):
    metadata = replace(BuiltinBaselineProvider().metadata(), **{field: value})
    assert fingerprint(phase1a_case) != fingerprint(phase1a_case, metadata=metadata)


def test_provider_id_changes_fingerprint(phase1a_case):
    config = replace(phase1a_case[2], provider_id="other-provider")
    metadata = replace(BuiltinBaselineProvider().metadata(), provider_id="other-provider")
    assert fingerprint(phase1a_case) != fingerprint(phase1a_case, config=config, metadata=metadata)


def test_integer_float_and_bool_params_remain_distinct(phase1a_case):
    values = [
        fingerprint(phase1a_case, config=replace(phase1a_case[2], params={"x": value}))
        for value in (1, 1.0, True)
    ]
    assert len(set(values)) == 3


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object(), b"bytes", Fraction(1, 3)])
def test_fingerprint_rejects_noncanonical_values(phase1a_case, value):
    config = replace(phase1a_case[2], params={"x": value})
    with pytest.raises(ValueError, match="fingerprint"):
        fingerprint(phase1a_case, config=config)


def test_fitted_time_uuid_and_context_refresh_leave_parameters_unchanged(phase1a_case):
    data, ds, config, ctx = phase1a_case
    config = replace(config, interval_levels=(0.8,))
    provider = BuiltinBaselineProvider()
    train = data[data.ds.le(pd.Timestamp(ds.train_end))]
    model = provider.fit_parameters(train, ds, config, ctx)
    repeated = provider.fit_parameters(train, ds, config, ctx)
    assert model.model_id != repeated.model_id
    assert model.parameter_fingerprint == repeated.parameter_fingerprint
    altered = replace(model, model_id="different", fitted_at=datetime(2020, 1, 1, tzinfo=UTC))
    assert altered.parameter_fingerprint == model.parameter_fingerprint
    assert model.weights_id is None and model.artifact_uri is None
    assert model.preprocessing_version == config.preprocessing_version
    assert model.train_start_date == ds.train_start
    before = deepcopy(model.state)
    for origin in ds.origin_dates():
        context = ctx.for_origin(origin)
        provider.refresh_context(model, data[data.ds.le(pd.Timestamp(origin))], origin, context)
    for uid, series in before.pop("train_series").items():
        pd.testing.assert_series_equal(series, model.state["train_series"][uid])
    assert before == {k: v for k, v in model.state.items() if k != "train_series"}
    assert model.parameter_fingerprint == repeated.parameter_fingerprint
