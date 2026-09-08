"""RunStoreをpollする独立Workerプロセスのentry point。"""

from __future__ import annotations

import argparse
import importlib
import time
from collections.abc import Callable
from pathlib import Path

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


def work_once(store: RunStore, execute: OriginExecutor, worker_id: str) -> int:
    processed = 0
    for run_id, fingerprint in store.list_runnable_runs():
        resume_run(store, run_id, fingerprint, execute, worker_id=worker_id)
        processed += 1
    return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    backend = parser.add_mutually_exclusive_group(required=True)
    backend.add_argument("--sqlite", type=Path)
    backend.add_argument("--postgres-dsn")
    parser.add_argument("--executor", required=True)
    parser.add_argument("--worker-id", default="worker-1")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    store = SqliteRunStore(args.sqlite) if args.sqlite else PostgresRunStore(args.postgres_dsn)
    execute = load_executor(args.executor)
    while True:
        work_once(store, execute, args.worker_id)
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
