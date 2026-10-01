"""Background Portable worker using the existing provider executor and run ledger."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.executors import BuiltinBaselineExecutor
from forecast_provider.jobs import SqliteRunStore, resume_run

LOG = logging.getLogger("portable.production_worker")


class PortableProductionWorker:
    def __init__(self, database: Path, artifact_root: Path, work_root: Path) -> None:
        self.database = database
        self.artifact_root = artifact_root
        self.work_root = work_root
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self._errors: dict[str, str] = {}

    def submit(self, run_id: str) -> bool:
        with self._lock:
            if run_id in self._active:
                return False
            store = SqliteRunStore(self.database)
            run = store.get_run(run_id)
            if run is None or run.status not in {"QUEUED", "RUNNING"}:
                return False
            self._active.add(run_id)
            self._errors.pop(run_id, None)
        threading.Thread(
            target=self._run,
            args=(run_id, run.condition_fingerprint),
            name=f"portable-production-{run_id[:8]}",
            daemon=True,
        ).start()
        return True

    def error(self, run_id: str) -> str | None:
        with self._lock:
            return self._errors.get(run_id)

    def _run(self, run_id: str, fingerprint: str) -> None:
        retry = False
        try:
            runs = SqliteRunStore(self.database)
            executor = BuiltinBaselineExecutor(
                runs,
                SqliteCatalogStore(self.database),
                self.artifact_root,
                self.work_root,
            )
            status = resume_run(
                runs,
                run_id,
                fingerprint,
                executor,
                worker_id="PORTABLE_PRODUCTION_BASELINE",
            )
            retry = status == "RUNNING"
        except Exception:
            LOG.exception("portable production worker failed run_id=%s", run_id)
            with self._lock:
                self._errors[run_id] = "予測Workerで処理できませんでした"
        finally:
            with self._lock:
                self._active.discard(run_id)
        if retry:
            timer = threading.Timer(1, self.submit, args=(run_id,))
            timer.daemon = True
            timer.start()
