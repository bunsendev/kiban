"""Subprocess used to verify the Job Object after launcher-like forced termination."""

import secrets
import sys
import time
from pathlib import Path

from portable.launcher.main import start_server
from portable.runtime.paths import DataPaths
from portable.runtime.windows import ChildJob, SingleInstance

root = Path(sys.argv[1])
paths = DataPaths(root)
paths.ensure()
with SingleInstance(root):
    job = ChildJob()
    child, port = start_server(paths, job, secrets.token_urlsafe(24))
    (root / "child.pid").write_text(f"{child.pid},{port}", encoding="ascii")
    while True:
        time.sleep(1)
