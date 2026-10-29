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
import threading
import time
import tkinter as tk
import traceback
import urllib.error
import webbrowser
from pathlib import Path
from tkinter import messagebox

import uvicorn

from portable import APP_VERSION
from portable.runtime.installation import MODES, setup_profile
from portable.runtime.local_http import request_json
from portable.runtime.paths import DataPaths
from portable.runtime.windows import AlreadyRunning, ChildJob, SingleInstance

LOG = logging.getLogger("portable.launcher")
PORTS = range(48150, 48181)
STARTUP_TIMEOUT = 45


class StartupCancelled(RuntimeError):
    pass


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


def initialize_runtime(paths: DataPaths, log_name: str) -> None:
    # Windows denies renaming Data if our own launcher/API log is already open.
    # The launcher must finish recovery before starting a child whose stdout is
    # also redirected to Data/Logs/api.log.
    from portable.api.app import recover_data

    recover_data(paths.root)
    paths.ensure()
    setup_logging(paths.logs / log_name)


def available_ports():
    for port in PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        yield port


def _terminate(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def start_server(paths: DataPaths, job: ChildJob, token: str, *, progress=None, cancelled=None):
    command = (
        [sys.executable]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "portable.launcher.main"]
    )
    command += ["--server", "--data-root", str(paths.root)]
    environment = os.environ.copy()
    environment["PORTABLE_CONTROL_TOKEN"] = token
    started = time.monotonic()
    deadline = started + STARTUP_TIMEOUT
    last_probe = "NO_AVAILABLE_PORT"
    for port in available_ports():
        if cancelled and cancelled():
            raise StartupCancelled()
        if time.monotonic() >= deadline:
            break
        if progress:
            progress(f"内部サーバーを起動しています（ポート {port}）")
        LOG.info("api_starting port=%s transport=direct_loopback", port)
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
        adopted = False
        previous_probe = None
        try:
            job.add(child.pid)
            while time.monotonic() < deadline:
                if progress:
                    progress(f"起動を確認しています（経過 {int(time.monotonic()-started)}秒）")
                if cancelled and cancelled():
                    raise StartupCancelled()
                if child.poll() is not None:
                    last_probe = "CHILD_EXITED"
                    break
                stage = "READY"
                diagnostic = "none"
                try:
                    # Keep GUI cancellation responsive even if a local connection is denied.
                    timeout = min(0.5, max(0.01, deadline-time.monotonic()))
                    ready = request_json(port, "/ready", timeout=timeout)
                    if ready.get("ready") is not True or ready.get("version") != APP_VERSION:
                        last_probe = "READY_NOT_CURRENT"
                    else:
                        stage = "CONTROL"
                        state = request_json(port, "/api/control/status", token=token,
                                             timeout=min(0.5, max(0.01, deadline-time.monotonic())))
                        if type(state.get("active")) is int and state["active"] >= 0:
                            adopted = True
                            LOG.info("api_startup_verified pid=%s port=%s elapsed=%.1f",
                                     child.pid, port, time.monotonic()-started)
                            return child, port
                        last_probe = "CONTROL_INVALID_RESPONSE"
                except urllib.error.HTTPError as exc:
                    last_probe = f"{stage}_HTTP_{exc.code}"
                    diagnostic = _probe_diagnostic(exc)
                except (OSError, ValueError) as exc:
                    # Exception text can contain proxy credentials/response bodies. Never log it.
                    last_probe = f"{stage}_{type(exc).__name__}"
                    diagnostic = _probe_diagnostic(exc)
                if last_probe != previous_probe:
                    LOG.warning("api_probe_failed pid=%s port=%s reason=%s diagnostic=%s",
                                child.pid, port, last_probe, diagnostic)
                    previous_probe = last_probe
                time.sleep(0.2)
            if child.poll() is None:
                # A listening child that fails readiness is not a reason to start 30 more.
                LOG.error("api_startup_timeout pid=%s port=%s reason=%s elapsed=%.1f",
                          child.pid, port, last_probe, time.monotonic()-started)
                break
            LOG.error("api_exited pid=%s status=%s port=%s", child.pid, child.returncode, port)
        finally:
            if not adopted:
                _terminate(child)
    LOG.error("api_startup_failed reason=%s elapsed=%.1f", last_probe, time.monotonic()-started)
    raise RuntimeError(f"PORTABLE-START-001: ローカルAPIを起動できません ({last_probe})")


def _probe_diagnostic(exc):
    # Include code locations and numeric OS codes, never messages/paths/response bodies.
    frames = ">".join(f"{Path(f.f_code.co_filename).name}:{f.f_code.co_name}:{line}"
                      for f, line in traceback.walk_tb(exc.__traceback__))
    errno = getattr(exc, "errno", None)
    winerror = getattr(exc, "winerror", None)
    return (f"phase={getattr(exc, 'portable_local_phase', 'UNKNOWN')}"
            f",errno={errno if type(errno) is int else 'none'}"
            f",winerror={winerror if type(winerror) is int else 'none'},frames={frames}")


def reopen_existing(paths):
    from portable.runtime.feedback_admin import instance_id
    from portable.runtime.installation import load_profile

    expected = instance_id(paths)
    for port in PORTS:
        try:
            value = request_json(port, "/api/operations/instance", timeout=0.15)
            if value.get("instance_id") != expected:
                continue
            ready = request_json(port, "/ready", timeout=0.15)
            if ready.get("ready") is not True:
                continue
            profile = load_profile(paths.root)
            page = "/field" if profile and profile["mode"] == "FIELD" else "/"
            return bool(webbrowser.open(f"http://127.0.0.1:{port}{page}"))
        except (OSError, ValueError):
            continue
    return False


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
    app = None
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
    try:
        with SingleInstance(paths.root):
            initialize_runtime(paths, "launcher.log")
            LOG.info("startup app=%s windows=%s", APP_VERSION, platform.platform())
            profile = setup_profile(paths.root)
            if profile is None:
                return 0
            LOG.info("installation=%s mode=%s", profile["installation_id"], profile["mode"])
            job = ChildJob()
            child = None
            try:
                token = secrets.token_urlsafe(32)
                app = tk.Tk()
                app.title("ブンセン予測 起動中")
                app.geometry("480x300")
                tk.Label(app, text="ブンセン予測を起動しています", font=("Yu Gothic UI", 13)).pack(
                    pady=15
                )
                startup_text = tk.Label(app, text="内部サーバーの確認は最大約45秒です。")
                startup_text.pack(pady=12)
                cancelled = False

                def cancel_startup():
                    nonlocal cancelled
                    cancelled = True
                    startup_text.config(text="起動を中止しています…")

                tk.Button(app, text="起動を中止する", command=cancel_startup).pack(pady=10)
                app.protocol("WM_DELETE_WINDOW", cancel_startup)

                def progress(text):
                    startup_text.config(text=text)
                    app.update()

                progress("内部サーバーを準備しています…")
                child, port = start_server(paths, job, token, progress=progress,
                                           cancelled=lambda: cancelled)
                LOG.info("api_ready pid=%s port=%s", child.pid, port)
                for widget in app.winfo_children():
                    widget.destroy()
                app.title(f"ブンセン予測 {MODES[profile['mode']]} / {profile['terminal_name']}")
                app.geometry("480x300")
                tk.Label(app, text="ブンセン予測を起動しました", font=("Yu Gothic UI", 13)).pack(
                    pady=15
                )
                entry_path = "/field" if profile["mode"] == "FIELD" else "/"
                browser_url = f"http://127.0.0.1:{port}{entry_path}"
                tk.Label(app, text=f"ブラウザー: {browser_url}").pack()

                def open_browser():
                    webbrowser.open(browser_url)

                tk.Button(app, text="画面を開く", command=open_browser).pack(pady=7)

                def open_incoming():
                    try:
                        os.startfile(paths.incoming)  # type: ignore[attr-defined]
                    except OSError:
                        LOG.exception("incoming_folder_open_failed")
                        messagebox.showerror(
                            "ブンセン予測",
                            "投入フォルダを開けません。Data/Incomingを確認してください。",
                        )

                tk.Button(app, text="投入フォルダを開く", command=open_incoming).pack()
                closing = False
                finish_text = tk.Label(app, text="")
                finish_text.pack()

                def finish():
                    nonlocal closing
                    if closing:
                        return
                    closing = True
                    finish_text.config(text="ログを送信しています。失敗分は次回再送します。")

                    def send_then_close():
                        try:
                            request_json(
                                port,
                                "/api/control/finish-day",
                                token=token,
                                method="POST",
                                timeout=60,
                            )
                        except Exception:
                            LOG.warning("feedback_retained_for_retry")
                        app.after(0, app.destroy)

                    threading.Thread(target=send_then_close, daemon=True).start()

                tk.Button(app, text="終了（ログ送信）", command=finish).pack()
                app.protocol("WM_DELETE_WINDOW", finish)

                def monitor():
                    nonlocal closing
                    if closing:
                        return
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
                        try:
                            state = request_json(port, "/api/control/status", token=token)
                            if state.get("update_requested"):
                                from portable.runtime.update_apply import spawn_helper

                                spawn_helper(bundle_root(), state["update_requested"])
                                closing = True
                                app.destroy()
                                return
                        except Exception:
                            LOG.warning("update_monitor_unavailable")
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
        if not reopen_existing(paths):
            messagebox.showinfo("ブンセン予測", str(exc) + "\n"
                                "起動処理中の場合は、起動中の画面でお待ちください。\n"
                                "応答がない場合は、Data/Logsを管理担当者へ渡してください。")
        return 0
    except StartupCancelled:
        LOG.info("startup_cancelled")
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
    finally:
        if app is not None:
            try:
                app.destroy()
            except tk.TclError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--feedback-admin", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--apply-update", type=Path)
    parser.add_argument("--stage")
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    if args.feedback_admin:
        from portable.runtime.feedback_admin import open_settings
        return open_settings(bundle_root())
    if args.apply_update:
        from portable.runtime.update_apply import run

        if not args.stage or not args.parent_pid:
            return 2
        run(args.apply_update, args.stage, args.parent_pid)
        return 0
    if args.server:
        if not args.port or not args.data_root or args.port not in PORTS:
            return 2
        paths = DataPaths(args.data_root)
        initialize_runtime(paths, "api-server.log")
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
