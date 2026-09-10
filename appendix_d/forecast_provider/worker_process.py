"""RunStoreをpollする独立Workerプロセスのentry point。"""

from __future__ import annotations

import argparse
import importlib
import time
from collections.abc import Callable
from pathlib import Path

from .catalog import PostgresCatalogStore, SqliteCatalogStore
from .executors import BuiltinBaselineExecutor, StatsForecastETSExecutor
from .jobs import PostgresRunStore, SqliteRunStore, resume_run
from .jobs.contracts import OriginExecutor, RunStore


def load_executor(spec: str) -> OriginExecutor:
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("executorはmodule:function形式です")
    value = getattr(importlib.import_module(module_name), attribute)
    if not isinstance(value, Callable):
        raise TypeError("executorは呼出可能でなければなりません")
    return value


def work_once(
    store: RunStore, execute: OriginExecutor, worker_id: str, max_origins: int | None = None
) -> int:
    processed = 0
    for run_id, fingerprint in store.list_runnable_runs():
        resume_run(
            store,
            run_id,
            fingerprint,
            execute,
            worker_id=worker_id,
            max_origins=max_origins,
        )
        processed += 1
    return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    backend = parser.add_mutually_exclusive_group(required=True)
    backend.add_argument("--sqlite", type=Path)
    backend.add_argument("--postgres-dsn")
    executor = parser.add_mutually_exclusive_group(required=True)
    executor.add_argument("--executor")
    executor.add_argument("--builtin-baseline", action="store_true")
    executor.add_argument("--statsforecast-ets", action="store_true")
    parser.add_argument("--artifact-root", type=Path, default=Path("artifact_output/objects"))
    parser.add_argument("--work-root", type=Path, default=Path("worker_output"))
    parser.add_argument("--worker-id", default="worker-1")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-origins", type=int)
    args = parser.parse_args(argv)
    if args.max_origins is not None and args.max_origins <= 0:
        parser.error("--max-originsは正数です")
    if args.sqlite:
        store = SqliteRunStore(args.sqlite)
        catalog = SqliteCatalogStore(args.sqlite)
    else:
        store = PostgresRunStore(args.postgres_dsn)
        catalog = PostgresCatalogStore(args.postgres_dsn)
    if args.builtin_baseline:
        execute = BuiltinBaselineExecutor(store, catalog, args.artifact_root, args.work_root)
    elif args.statsforecast_ets:
        execute = StatsForecastETSExecutor(store, catalog, args.artifact_root, args.work_root)
    else:
        execute = load_executor(args.executor)
    while True:
        work_once(store, execute, args.worker_id, args.max_origins)
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
