"""Phase 1C: 起点transaction、再開、重複防止。"""

from datetime import date
from decimal import Decimal

import pytest

from forecast_provider.errors import ContractViolationError, RetryableProviderError
from forecast_provider.jobs import (
    Expectation,
    ForecastValue,
    OriginDefinition,
    OriginOutput,
    RunDefinition,
    SqliteRunStore,
    StaleLeaseError,
    resume_run,
)
from forecast_provider.run_context import cutoff_for_origin


def origin(day: int) -> OriginDefinition:
    value = date(2026, 1, day)
    return OriginDefinition(value, cutoff_for_origin(value))


def expectation(day: int) -> Expectation:
    return Expectation("A", date(2026, 1, day), date(2026, 1, day + 1), 1)


def point(day: int, raw: str = "2.5") -> ForecastValue:
    value = Decimal(raw)
    return ForecastValue(
        "A",
        date(2026, 1, day),
        date(2026, 1, day + 1),
        1,
        "POINT",
        None,
        value,
        max(value, Decimal(0)),
    )


def make_store(tmp_path, days=(1, 2)) -> SqliteRunStore:
    store = SqliteRunStore(tmp_path / "runs.sqlite3")
    store.create_run(
        RunDefinition("run-1", "experiment-1", "fingerprint-1", "builtin-baseline", "ma", 7),
        tuple(origin(day) for day in days),
        tuple(expectation(day) for day in days),
    )
    return store


def test_resume_skips_completed_origin_after_worker_interruption(tmp_path):
    store = make_store(tmp_path)
    store.start_or_resume("run-1", "fingerprint-1")
    first = store.claim_next_origin("run-1")
    assert first is not None
    store.complete_origin(first, OriginOutput((point(1),), "model:1", "context:1"))
    interrupted = store.claim_next_origin("run-1")
    assert interrupted is not None

    executed = []

    def execute(lease):
        executed.append(lease.origin.origin_date.day)
        return OriginOutput((point(lease.origin.origin_date.day),))

    assert resume_run(store, "run-1", "fingerprint-1", execute) == "SUCCEEDED"
    assert executed == [2]
    assert len(store.rows("forecast_values")) == 2
    assert [row["attempt"] for row in store.rows("forecast_origins")] == [1, 2]


def test_origin_result_and_state_are_atomic(tmp_path):
    store = make_store(tmp_path, days=(1,))
    store.start_or_resume("run-1", "fingerprint-1")
    lease = store.claim_next_origin("run-1")
    assert lease is not None
    with pytest.raises(ContractViolationError):
        store.complete_origin(lease, OriginOutput(()))
    assert store.rows("forecast_values") == []
    assert store.rows("forecast_origins")[0]["status"] == "RUNNING"


def test_stale_attempt_cannot_publish_or_duplicate_output(tmp_path):
    store = make_store(tmp_path, days=(1,))
    store.start_or_resume("run-1", "fingerprint-1")
    stale = store.claim_next_origin("run-1")
    assert stale is not None
    store.start_or_resume("run-1", "fingerprint-1")
    current = store.claim_next_origin("run-1")
    assert current is not None
    with pytest.raises(StaleLeaseError):
        store.complete_origin(stale, OriginOutput((point(1),)))
    store.complete_origin(current, OriginOutput((point(1),)))
    with pytest.raises(StaleLeaseError):
        store.complete_origin(current, OriginOutput((point(1),)))
    assert len(store.rows("forecast_values")) == 1


def test_resume_rejects_changed_conditions_and_completed_run(tmp_path):
    store = make_store(tmp_path, days=(1,))
    with pytest.raises(ContractViolationError):
        store.start_or_resume("run-1", "different")
    assert (
        resume_run(
            store,
            "run-1",
            "fingerprint-1",
            lambda lease: OriginOutput((point(lease.origin.origin_date.day),)),
        )
        == "SUCCEEDED"
    )
    with pytest.raises(ContractViolationError):
        store.start_or_resume("run-1", "fingerprint-1")


def test_retryable_failure_gets_three_attempts_without_partial_values(tmp_path):
    store = make_store(tmp_path, days=(1,))
    attempts = []

    def fail(lease):
        attempts.append(lease.attempt)
        raise RetryableProviderError("temporary")

    assert resume_run(store, "run-1", "fingerprint-1", fail) == "FAILED"
    assert attempts == [1, 2, 3]
    assert len(store.rows("forecast_failures")) == 3
    assert store.rows("forecast_values") == []


def test_cancellation_stops_before_next_origin(tmp_path):
    store = make_store(tmp_path)
    store.request_cancellation("run-1")
    called = []
    status = resume_run(store, "run-1", "fingerprint-1", lambda lease: called.append(lease))
    assert status == "CANCELLED"
    assert called == []


def test_point_contract_and_artifact_references_are_persisted(tmp_path):
    store = make_store(tmp_path, days=(1,))
    store.start_or_resume("run-1", "fingerprint-1")
    lease = store.claim_next_origin("run-1")
    assert lease is not None
    invalid = point(1, "-1")
    invalid = ForecastValue(
        invalid.unique_id,
        invalid.origin_date,
        invalid.target_date,
        invalid.horizon,
        invalid.forecast_kind,
        invalid.quantile,
        invalid.yhat_raw,
        Decimal("-1"),
    )
    with pytest.raises(ContractViolationError):
        store.complete_origin(lease, OriginOutput((invalid,)))
    store.complete_origin(lease, OriginOutput((point(1),), "sha256:model", "sha256:context"))
    row = store.rows("forecast_origins")[0]
    assert (row["model_artifact"], row["context_artifact"]) == (
        "sha256:model",
        "sha256:context",
    )
