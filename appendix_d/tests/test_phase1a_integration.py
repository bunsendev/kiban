"""runnerとProvider境界の時点契約。既存の予測・評価規則は回帰試験で維持する。"""

from dataclasses import replace
from datetime import timedelta

import pandas as pd
import pytest
from test_builtin_baseline import make_future

from forecast_provider.errors import ContractViolationError
from forecast_provider.providers.builtin_baseline import BuiltinBaselineProvider
from forecast_provider.runner import run_fixed_baseline


def test_runner_delivers_fit_and_each_origin_context(phase1a_case, monkeypatch):
    data, ds, config, parent = phase1a_case
    calls = {"fit": [], "refresh_context": [], "predict": []}
    original_fit = BuiltinBaselineProvider.fit_parameters

    def fit(self, train, dataset, config, context):
        calls["fit"].append(context)
        return original_fit(self, train, dataset, config, context)

    monkeypatch.setattr(BuiltinBaselineProvider, "fit_parameters", fit)
    for method in ("refresh_context", "predict"):
        original = getattr(BuiltinBaselineProvider, method)

        def spy(self, *args, _original=original, _method=method):
            calls[_method].append(args[-1])
            return _original(self, *args)

        monkeypatch.setattr(BuiltinBaselineProvider, method, spy)
    result = run_fixed_baseline(data, ds, config, parent, availability_mode="ASSUMED")
    assert result["status"] == "SUCCESS" and result["fit_calls"] == 1
    assert len(calls["fit"]) == 1
    assert calls["fit"][0].origin_date == ds.train_end
    assert calls["fit"][0].cutoff_at.isoformat() == "2026-01-01T00:00:00+09:00"
    assert [c.origin_date for c in calls["predict"]] == ds.origin_dates()
    assert len({id(c) for c in calls["predict"]}) == len(ds.origin_dates())
    for refresh, predict in zip(calls["refresh_context"], calls["predict"], strict=True):
        assert refresh is predict
        assert predict.cutoff_at.date() == predict.origin_date + timedelta(days=1)
        assert predict.cutoff_at.hour == predict.cutoff_at.minute == 0
        assert predict.logger is parent.logger
        assert predict.run_id == parent.run_id


@pytest.mark.parametrize(
    "dataset_mode,context_mode,argument_mode",
    [
        ("OBSERVED", "ASSUMED", "OBSERVED"),
        ("ASSUMED", "OBSERVED", "ASSUMED"),
        ("ASSUMED", "ASSUMED", "OBSERVED"),
    ],
)
def test_runner_rejects_mode_mismatch_before_provider_creation(
    phase1a_case, monkeypatch, dataset_mode, context_mode, argument_mode
):
    data, ds, config, context = phase1a_case

    def forbidden(*args):
        pytest.fail("Provider must not be created on mode mismatch")

    monkeypatch.setattr("forecast_provider.runner.registry.create", forbidden)
    with pytest.raises(ContractViolationError, match="availability_mode"):
        run_fixed_baseline(
            data,
            replace(ds, availability_mode=dataset_mode),
            config,
            replace(context, availability_mode=context_mode),
            availability_mode=argument_mode,
        )


@pytest.mark.parametrize("change", ["model", "origin", "cutoff"])
def test_predict_rejects_wrong_context_reference(phase1a_case, change):
    data, ds, config, ctx = phase1a_case
    provider = BuiltinBaselineProvider()
    train = data[data.ds.le(pd.Timestamp(ds.train_end))]
    model = provider.fit_parameters(train, ds, config, ctx)
    ref = provider.refresh_context(model, train, ds.train_end, ctx)
    changes = {
        "model": {"model_id": "wrong"},
        "origin": {"origin_date": ds.train_end + timedelta(days=1)},
        "cutoff": {"cutoff_at": ctx.cutoff_at + timedelta(seconds=1)},
    }
    wrong = replace(ref, **changes[change])
    with pytest.raises(ContractViolationError):
        provider.predict(
            model, wrong, make_future(ds.unique_ids, pd.Timestamp(ds.train_end), [1]), [1], ctx
        )


def test_runner_rejects_provider_returning_previous_origin(phase1a_case, monkeypatch):
    data, ds, config, ctx = phase1a_case
    original = BuiltinBaselineProvider.refresh_context
    first = []

    def reused(self, *args):
        if not first:
            first.append(original(self, *args))
        return first[0]

    monkeypatch.setattr(BuiltinBaselineProvider, "refresh_context", reused)
    with pytest.raises(ContractViolationError, match="origin_date"):
        run_fixed_baseline(data, ds, config, ctx, availability_mode="ASSUMED")


@pytest.mark.parametrize("change", ["cutoff", "mode", "origin"])
def test_direct_fit_rejects_wrong_time_contract(phase1a_case, change):
    data, ds, config, ctx = phase1a_case
    changes = {
        "cutoff": {"cutoff_at": ctx.cutoff_at + timedelta(days=1)},
        "mode": {"availability_mode": "OBSERVED"},
        "origin": {"origin_date": None},
    }
    with pytest.raises(ContractViolationError):
        BuiltinBaselineProvider().fit_parameters(
            data[data.ds.le(pd.Timestamp(ds.train_end))],
            ds,
            config,
            replace(ctx, **changes[change]),
        )


def test_direct_refresh_rejects_other_run_and_cutoff(phase1a_case):
    data, ds, config, ctx = phase1a_case
    provider = BuiltinBaselineProvider()
    train = data[data.ds.le(pd.Timestamp(ds.train_end))]
    model = provider.fit_parameters(train, ds, config, ctx)
    with pytest.raises(ContractViolationError, match="run/experiment"):
        provider.refresh_context(model, train, ds.train_end, replace(ctx, run_id="other"))
    with pytest.raises(ContractViolationError, match="cutoff_at"):
        provider.refresh_context(
            model, train, ds.train_end, replace(ctx, cutoff_at=ctx.cutoff_at + timedelta(hours=1))
        )


def test_observed_point_runner_remains_available(phase1a_case):
    data, ds, config, ctx = phase1a_case
    data = data.copy()
    data["available_at"] = (data.ds + pd.Timedelta(days=1)).dt.tz_localize("Asia/Tokyo")
    result = run_fixed_baseline(
        data,
        replace(ds, availability_mode="OBSERVED"),
        config,
        replace(ctx, availability_mode="OBSERVED"),
        availability_mode="OBSERVED",
    )
    assert result["status"] == "SUCCESS"
    assert result["predictions"].forecast_kind.eq("POINT").all()


@pytest.mark.parametrize("value", [None, pd.NaT, pd.Timestamp("2026-01-01"), "2026-01-01"])
def test_context_ref_rejects_invalid_cutoff(phase1a_case, value):
    from forecast_provider import ContextRef

    origin = phase1a_case[1].train_end
    with pytest.raises(ValueError, match="cutoff_at"):
        ContextRef("context", "model", origin, origin, cutoff_at=value)
