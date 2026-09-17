"""Phase 3F Provider Worker heartbeatとキュー診断。"""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import Expectation, OriginDefinition, RunDefinition, SqliteRunStore
from forecast_provider.run_context import cutoff_for_origin
from forecast_provider.worker_status import (
    SqliteWorkerStatusStore,
    StaleWorkerHeartbeat,
    WorkerState,
    WorkerStatusService,
)


def _queued_run(
    runs: SqliteRunStore,
    provider_id: str = "builtin-baseline",
    run_id: str = "run-1",
) -> None:
    origin = date(2026, 1, 1)
    runs.create_run(
        RunDefinition(
            run_id,
            f"experiment-{run_id}",
            f"fingerprint-{run_id}",
            provider_id,
            "model-1",
            7,
        ),
        (OriginDefinition(origin, cutoff_for_origin(origin)),),
        (Expectation("A", origin, date(2026, 1, 2), 1),),
    )


def test_worker_registration_fences_replaced_process(tmp_path):
    store = SqliteWorkerStatusStore(tmp_path / "workers.sqlite3")
    now = datetime(2026, 9, 17, tzinfo=UTC)
    store.register("worker-1", "instance-old", "builtin-baseline", now=now)
    working = store.heartbeat(
        "worker-1",
        "instance-old",
        WorkerState.WORKING,
        "run-1",
        now=now + timedelta(seconds=1),
    )
    assert working.current_run_id == "run-1"

    replacement = store.register(
        "worker-1", "instance-new", "builtin-baseline", now=now + timedelta(seconds=2)
    )

    assert replacement.state == WorkerState.IDLE
    assert replacement.started_at == now + timedelta(seconds=2)
    with pytest.raises(StaleWorkerHeartbeat):
        store.heartbeat("worker-1", "instance-old", WorkerState.IDLE)


def test_provider_status_combines_heartbeat_and_complete_queue_counts(tmp_path):
    database = tmp_path / "status.sqlite3"
    runs = SqliteRunStore(database)
    workers = SqliteWorkerStatusStore(database)
    _queued_run(runs)
    for index in range(200):
        _queued_run(runs, run_id=f"run-extra-{index:03d}")
    now = datetime(2026, 9, 17, 0, 0, tzinfo=UTC)
    workers.register("baseline-1", "instance-1", "builtin-baseline", now=now)
    service = WorkerStatusService(runs, workers, stale_seconds=45)

    online = next(
        item for item in service.list_status(now=now) if item["provider_id"] == "builtin-baseline"
    )
    stale = next(
        item
        for item in service.list_status(now=now + timedelta(seconds=46))
        if item["provider_id"] == "builtin-baseline"
    )

    assert online["status"] == "ONLINE"
    assert online["queued_runs"] == 201
    assert online["running_runs"] == 0
    assert online["workers"][0]["liveness"] == "ONLINE"
    assert stale["status"] == "STALE"

    workers.heartbeat(
        "baseline-1", "instance-1", WorkerState.WORKING, "run-1", now=now + timedelta(seconds=47)
    )
    working = next(
        item
        for item in service.list_status(now=now + timedelta(seconds=48))
        if item["provider_id"] == "builtin-baseline"
    )
    assert working["status"] == "WORKING"
    assert working["workers"][0]["current_run_id"] == "run-1"


def test_worker_status_api_is_read_protected(tmp_path):
    database = tmp_path / "api.sqlite3"
    workers = SqliteWorkerStatusStore(database)
    workers.register("baseline-1", "instance-1", "builtin-baseline")
    app = create_app(
        SqliteRunStore(database),
        SqliteCatalogStore(database),
        "token",
        worker_status=workers,
    )
    api = TestClient(app)

    assert api.get("/api/worker-status").status_code == 401
    response = api.get("/api/worker-status", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    baseline = next(item for item in response.json() if item["provider_id"] == "builtin-baseline")
    assert baseline["status"] == "ONLINE"
    assert baseline["workers"][0]["worker_id"] == "baseline-1"
    assert "instance_id" not in baseline["workers"][0]
