"""Single click launcher and local API subprocess supervisor."""

import argparse
import logging
import os
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import messagebox

import uvicorn

from portable import APP_VERSION
from portable.runtime.paths import DataPaths
from portable.runtime.windows import AlreadyRunning, ChildJob, SingleInstance

LOG = logging.getLogger("portable.launcher")
PORTS = range(48150, 48181)


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[2] / ".portable-p1"


def setup_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8")],
        force=True,
    )


def available_ports():
    for port in PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        yield port


def request_json(port: int, path: str, *, token: str | None = None, method: str = "GET") -> dict:
    headers = {"X-Portable-Control": token} if token else {}
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        import json

        return json.load(response)


def start_server(paths: DataPaths, job: ChildJob, token: str):
    command = (
        [sys.executable]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "portable.launcher.main"]
    )
    command += ["--server", "--data-root", str(paths.root)]
    environment = os.environ.copy()
    environment["PORTABLE_CONTROL_TOKEN"] = token
    for port in available_ports():
        with (paths.logs / "api.log").open("a", encoding="utf-8") as log_file:
            child = subprocess.Popen(
                [*command, "--port", str(port)],
                cwd=str(
                    bundle_root() / "App"
                    if getattr(sys, "frozen", False)
                    else Path(__file__).resolve().parents[2]
                ),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        try:
            job.add(child.pid)
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    break
                try:
                    if request_json(port, "/ready").get("ready") and "active" in request_json(
                        port, "/api/control/status", token=token
                    ):
                        return child, port
                except (OSError, ValueError, urllib.error.URLError):
                    pass
                time.sleep(0.2)
        except Exception:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            raise
        finally:
            if child.poll() is not None:
                LOG.error("api_exited pid=%s status=%s port=%s", child.pid, child.returncode, port)
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
    raise RuntimeError("PORTABLE-START-001: ローカルAPIを起動できません")


def stop_server(child: subprocess.Popen, port: int, token: str) -> None:
    LOG.info("shutdown_requested pid=%s", child.pid)
    try:
        request_json(port, "/api/control/drain", token=token, method="POST")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if request_json(port, "/api/control/status", token=token).get("active") == 0:
                break
            time.sleep(0.3)
    except (OSError, urllib.error.URLError, ValueError):
        LOG.warning("api_drain_unavailable")
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
    LOG.info("shutdown_complete pid=%s status=%s", child.pid, child.returncode)


def launch() -> int:
    root = bundle_root()
    paths = DataPaths(root / "Data")
    try:
        paths.ensure()
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "bunsen-portable-p1-start-error.txt"
        fallback.write_text(traceback.format_exc(), encoding="utf-8")
        messagebox.showerror(
            "ブンセン予測",
            "保存先に書き込めないため起動できません。\n"
            "エラーコード: PORTABLE-START-003\n"
            f"診断情報: {fallback}",
        )
        return 1
    setup_logging(paths.logs / "launcher.log")
    LOG.info("startup app=%s windows=%s", APP_VERSION, platform.platform())
    try:
        with SingleInstance(paths.root):
            job = ChildJob()
            child = None
            try:
                token = secrets.token_urlsafe(32)
                child, port = start_server(paths, job, token)
                LOG.info("api_ready pid=%s port=%s", child.pid, port)
                app = tk.Tk()
                app.title("ブンセン予測 Portable P1")
                app.geometry("430x190")
                tk.Label(app, text="ブンセン予測を起動しました", font=("Yu Gothic UI", 13)).pack(
                    pady=15
                )
                tk.Label(app, text=f"ブラウザー: http://127.0.0.1:{port}/").pack()

                def open_browser():
                    webbrowser.open(f"http://127.0.0.1:{port}/")

                tk.Button(app, text="画面を開く", command=open_browser).pack(pady=7)
                tk.Button(app, text="終了", command=app.destroy).pack()

                def monitor():
                    if child.poll() is not None:
                        LOG.error(
                            "api_unexpected_exit pid=%s status=%s", child.pid, child.returncode
                        )
                        messagebox.showerror(
                            "ブンセン予測",
                            "動作を継続できません。\nPORTABLE-START-002\n管理担当者へLogsを渡してください。",
                        )
                        app.destroy()
                    else:
                        app.after(1000, monitor)

                app.after(1000, monitor)
                open_browser()
                app.mainloop()
                return 0
            finally:
                if child:
                    stop_server(child, port, token)
                job.close()
                LOG.info("launcher_exit")
    except AlreadyRunning as exc:
        messagebox.showinfo("ブンセン予測", str(exc))
        return 0
    except Exception:
        LOG.exception("launcher_failed code=PORTABLE-START-001")
        messagebox.showerror(
            "ブンセン予測",
            "ブンセン予測を起動できませんでした。\n"
            "エラーコード: PORTABLE-START-001\n"
            "Data/Logsを管理担当者に渡してください。",
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    if args.server:
        if not args.port or not args.data_root or args.port not in PORTS:
            return 2
        paths = DataPaths(args.data_root)
        paths.ensure()
        setup_logging(paths.logs / "api-server.log")
        from portable.api.app import create_app

        uvicorn.run(
            create_app(paths.root, control_token=os.environ.get("PORTABLE_CONTROL_TOKEN")),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
            log_config=None,
        )
        return 0
    return launch()


if __name__ == "__main__":
    sys.exit(main())
