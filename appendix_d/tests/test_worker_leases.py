"""Phase 1D: lease、heartbeat、timeout。"""

import time
from datetime import UTC, datetime, timedelta

import pytest
from test_job_resume import make_store, point

from forecast_provider.jobs import OriginOutput, StaleLeaseError, resume_run
from forecast_provider.worker_process import work_once


def test_two_workers_cannot_claim_same_origin(tmp_path):
    store = make_store(tmp_path, days=(1,))
    store.start_or_resume("run-1", "fingerprint-1")
    first = store.claim_next_origin("run-1", "worker-a", 60)
    assert first is not None
    assert store.claim_next_origin("run-1", "worker-b", 60) is None
    assert store.finish_run("run-1") == "RUNNING"


def test_heartbeat_extends_lease_and_wrong_worker_is_stale(tmp_path):
    store = make_store(tmp_path, days=(1,))
    store.start_or_resume("run-1", "fingerprint-1")
    lease = store.claim_next_origin("run-1", "worker-a", 1)
    assert lease is not None
    extended = store.heartbeat(lease, 60)
    assert extended.leased_until > lease.leased_until
    wrong = type(lease)(
        lease.run_id,
        lease.origin,
        lease.attempt,
        "worker-b",
        lease.lease_token,
        lease.leased_until,
    )
    with pytest.raises(StaleLeaseError):
        store.heartbeat(wrong, 60)


def test_expired_lease_is_reclaimed_with_new_attempt(tmp_path):
    store = make_store(tmp_path, days=(1,))
    store.start_or_resume("run-1", "fingerprint-1")
    old = store.claim_next_origin("run-1", "worker-a", 60)
    assert old is not None
    future = old.leased_until + timedelta(seconds=1)
    assert store.reclaim_expired("run-1", now=future) == 1
    new = store.claim_next_origin("run-1", "worker-b", 60)
    assert new is not None and new.attempt == 2
    with pytest.raises(StaleLeaseError):
        store.complete_origin(old, OriginOutput((point(1),)))


def test_timeout_returns_without_waiting_for_late_executor(tmp_path):
    store = make_store(tmp_path, days=(1,))

    def slow(_lease):
        time.sleep(0.2)
        return OriginOutput((point(1),))

    started = datetime.now(UTC)
    status = resume_run(
        store,
        "run-1",
        "fingerprint-1",
        slow,
        origin_timeout_seconds=0.02,
        lease_seconds=1,
    )
    assert status == "FAILED"
    assert (datetime.now(UTC) - started).total_seconds() < 0.15
    assert store.rows("forecast_values") == []


def test_second_worker_does_not_finalize_run_owned_by_first_worker(tmp_path):
    store = make_store(tmp_path, days=(1,))
    store.start_or_resume("run-1", "fingerprint-1")
    assert store.claim_next_origin("run-1", "worker-a", 60) is not None
    assert work_once(store, lambda lease: OriginOutput((point(1),)), "worker-b") == 1
    snapshot = store.get_run("run-1")
    assert snapshot is not None and snapshot.status == "RUNNING"
