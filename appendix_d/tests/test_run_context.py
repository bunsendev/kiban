"""型と起点時点の契約。JST/UTCは同一の実時刻として比較する。"""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, tzinfo

import pandas as pd
import pytest
from test_builtin_baseline import make_context

from forecast_provider import RunContext
from forecast_provider.errors import ContractViolationError
from forecast_provider.failures import InMemoryFailureSink
from forecast_provider.run_context import RunContext as DefinedRunContext
from forecast_provider.run_context import cutoff_for_origin


class NoOffsetTimezone(tzinfo):
    def utcoffset(self, dt):
        return None


@pytest.mark.parametrize(
    "value",
    [
        None,
        pd.NaT,
        "2026-01-01T00:00+09:00",
        0,
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=NoOffsetTimezone()),
    ],
)
def test_cutoff_rejects_missing_naive_and_invalid_type(value):
    with pytest.raises(ValueError, match="cutoff_at"):
        replace(make_context(), cutoff_at=value)


@pytest.mark.parametrize("mode", [None, "", "observed", "INVALID", 1])
def test_availability_rejects_invalid_mode(mode):
    with pytest.raises(ValueError, match="availability_mode"):
        replace(make_context(), availability_mode=mode)


def test_context_derivation_preserves_shared_resources_and_parent():
    sink = InMemoryFailureSink()
    parent = replace(make_context(), failure_sink=sink, origin_date=None)
    first = parent.for_origin(date(2026, 1, 10))
    second = parent.for_origin(date(2026, 1, 20))
    assert RunContext is DefinedRunContext
    assert first.cutoff_at.isoformat() == "2026-01-11T00:00:00+09:00"
    assert second.cutoff_at.isoformat() == "2026-01-21T00:00:00+09:00"
    assert first.cutoff_at != second.cutoff_at
    for name in (
        "run_id",
        "experiment_id",
        "seed",
        "deadline",
        "input_dir",
        "output_dir",
        "resource_profile",
        "logger",
        "failure_sink",
        "availability_mode",
    ):
        assert getattr(first, name) == getattr(parent, name)
    assert first.logger is parent.logger
    assert first.failure_sink is sink
    assert parent.origin_date is None
    with pytest.raises(FrozenInstanceError):
        first.cutoff_at = second.cutoff_at


def test_cutoff_accepts_same_instant_in_utc_but_rejects_wrong_instant():
    context = make_context()
    utc = replace(context, cutoff_at=context.cutoff_at.astimezone(UTC))
    utc.validate_for_origin(context.origin_date, "ASSUMED")
    wrong = replace(context, cutoff_at=context.cutoff_at + timedelta(seconds=1))
    with pytest.raises(ContractViolationError, match="cutoff_at"):
        wrong.validate_for_origin(context.origin_date, "ASSUMED")


@pytest.mark.parametrize("origin", [None, pd.NaT, "2026-01-01", datetime(2026, 1, 1)])
def test_origin_derivation_rejects_non_date(origin):
    with pytest.raises(ValueError, match="origin_date"):
        cutoff_for_origin(origin)
