"""HTTP外の新しいPythonプロセスがrunを完了する。"""

import os
import subprocess
import sys
from pathlib import Path

from test_job_resume import make_store

from forecast_provider.jobs import SqliteRunStore


def test_independent_worker_process_executes_queued_run(tmp_path):
    database = tmp_path / "runs.sqlite3"
    make_store(tmp_path, days=(1,))
    generated = tmp_path / "worker_fixture.py"
    generated.write_text(
        """from datetime import timedelta
from decimal import Decimal
from forecast_provider.jobs import ForecastValue, OriginOutput

def execute(lease):
    origin = lease.origin.origin_date
    target = origin + timedelta(days=1)
    value = ForecastValue(
        'A', origin, target, 1, 'POINT', None, Decimal('1'), Decimal('1')
    )
    return OriginOutput((value,))
""",
        encoding="utf-8",
    )
    env = dict(os.environ)
    package_root = str(Path(__file__).parents[1])
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), package_root])
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "forecast_provider.worker_process",
            "--sqlite",
            str(database),
            "--executor",
            "worker_fixture:execute",
            "--worker-id",
            "process-worker",
            "--once",
        ],
        cwd=package_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    snapshot = SqliteRunStore(database).get_run("run-1")
    assert snapshot is not None and snapshot.status == "SUCCEEDED"
