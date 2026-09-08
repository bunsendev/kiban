"""新しいPythonプロセスで、再fitなしに復元して完全一致する。"""

import os
import subprocess
import sys
from pathlib import Path

from artifact_demo import save


def test_fresh_process_restores_without_parameter_fit(tmp_path):
    save(tmp_path)
    source = """
import sys
from pathlib import Path
from artifact_demo import restore
from forecast_provider.providers import builtin_baseline
def forbidden(*args, **kwargs):
    raise AssertionError('Restoration must not fit or recompute residuals')
builtin_baseline.BuiltinBaselineProvider.fit_parameters = forbidden
builtin_baseline._residual_quantiles = forbidden
restore(Path(sys.argv[1]))
"""
    result = subprocess.run(
        [sys.executable, "-c", source, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, PYTHONUTF8="1"),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "exact POINT/QUANTILE match" in result.stdout
    assert (tmp_path / "expected.csv").read_bytes() == (tmp_path / "restored.csv").read_bytes()
