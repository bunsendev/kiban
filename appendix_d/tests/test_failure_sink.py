"""既存errorsと外部sinkが同じ失敗を表し、契約違反を飲み込まない。"""

from dataclasses import replace

import pytest

from forecast_provider.errors import ContractViolationError, RetryableProviderError
from forecast_provider.failures import FailureSinkError, InMemoryFailureSink, record_failure
from forecast_provider.providers.builtin_baseline import BuiltinBaselineProvider
from forecast_provider.runner import run_fixed_baseline


@pytest.mark.parametrize("phase", ["fit_parameters", "predict"])
@pytest.mark.parametrize("exception_type", [RetryableProviderError, KeyError])
def test_sink_records_classified_and_unclassified_failures(
    phase1a_case, monkeypatch, phase, exception_type
):
    data, ds, config, ctx = phase1a_case
    sink = InMemoryFailureSink()
    ctx = replace(ctx, failure_sink=sink)
    original = getattr(BuiltinBaselineProvider, phase)
    calls = []
    cleanups = []

    def crash_once(self, *args):
        calls.append(args[-1])
        if len(calls) == 1:
            raise exception_type("simulated failure")
        return original(self, *args)

    monkeypatch.setattr(BuiltinBaselineProvider, phase, crash_once)
    monkeypatch.setattr(BuiltinBaselineProvider, "cleanup", lambda self, c: cleanups.append(c))
    result = run_fixed_baseline(data, ds, config, ctx, availability_mode="ASSUMED")
    assert len(sink.records) == 1 and cleanups == [ctx]
    record = sink.records[0]
    assert result["errors"] == [record.as_legacy_error()]
    assert record.run_id == ctx.run_id and record.experiment_id == ctx.experiment_id
    assert record.cutoff_at == calls[0].cutoff_at
    assert record.retryable is (exception_type is RetryableProviderError)
    assert (record.traceback is None) is (exception_type is RetryableProviderError)
    if exception_type is KeyError:
        assert record.error == "UNCLASSIFIED_ERROR" and "KeyError" in record.traceback
    if phase == "fit_parameters":
        assert record.origin_date is None
        assert result["status"] == "FAILED" and result["ledger"].status.eq("FAILED").all()
    else:
        assert record.origin_date == ds.train_end
        assert len(calls) == len(ds.origin_dates())
        assert result["status"] == "PARTIAL"


@pytest.mark.parametrize("phase", ["fit_parameters", "refresh_context", "predict"])
def test_contract_violation_bypasses_sink_and_cleans_up(phase1a_case, monkeypatch, phase):
    data, ds, config, ctx = phase1a_case
    sink = InMemoryFailureSink()
    ctx = replace(ctx, failure_sink=sink)
    cleanups = []

    def violate(self, *args):
        raise ContractViolationError("broken contract")

    monkeypatch.setattr(BuiltinBaselineProvider, phase, violate)
    monkeypatch.setattr(BuiltinBaselineProvider, "cleanup", lambda self, c: cleanups.append(c))
    with pytest.raises(ContractViolationError, match="broken contract"):
        run_fixed_baseline(data, ds, config, ctx, availability_mode="ASSUMED")
    assert sink.records == [] and cleanups == [ctx]


class BrokenSink:
    def record(self, failure):
        raise OSError("sink offline")


@pytest.mark.parametrize("phase", ["fit_parameters", "predict"])
def test_sink_failure_stops_and_preserves_original_record(phase1a_case, monkeypatch, phase):
    data, ds, config, ctx = phase1a_case
    ctx = replace(ctx, failure_sink=BrokenSink())
    cleanups, calls = [], []

    def crash(self, *args):
        calls.append(1)
        raise RetryableProviderError("provider offline")

    monkeypatch.setattr(BuiltinBaselineProvider, phase, crash)
    monkeypatch.setattr(BuiltinBaselineProvider, "cleanup", lambda self, c: cleanups.append(c))
    with pytest.raises(FailureSinkError) as caught:
        run_fixed_baseline(data, ds, config, ctx, availability_mode="ASSUMED")
    assert caught.value.record.message == "provider offline"
    assert isinstance(caught.value.__cause__, OSError)
    assert cleanups == [ctx] and len(calls) == 1


def test_sink_failure_does_not_erase_existing_error_list(phase1a_case):
    errors = []
    ctx = replace(phase1a_case[3], failure_sink=BrokenSink())
    with pytest.raises(FailureSinkError) as caught:
        record_failure(errors, ctx, None, KeyError("original failure"))
    assert errors == [caught.value.record.as_legacy_error()]
