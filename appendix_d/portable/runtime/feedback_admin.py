"""Short-lived setup session issued by an elevated local administrator command."""

import ctypes
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.request
import webbrowser

from portable.api.business_archive import atomic_json
from portable.runtime.paths import DataPaths


def is_admin():
    return os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def issue(paths):
    if not is_admin():
        raise PermissionError("Windows管理者による設定が必要です")
    token = secrets.token_urlsafe(32)
    atomic_json(
        paths.state / "feedback-admin-session.json",
        {
            "sha256": hashlib.sha256(token.encode()).hexdigest(),
            "expires": time.time() + 900,
        },
    )
    return token


def authorized(paths, token):
    if not token or len(token) > 200:
        return False
    try:
        value = json.loads((paths.state / "feedback-admin-session.json").read_text("utf-8"))
        return value["expires"] > time.time() and hmac.compare_digest(
            value["sha256"],
            hashlib.sha256(token.encode()).hexdigest(),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def instance_id(paths):
    return hashlib.sha256(str(paths.root).encode()).hexdigest()


def open_settings(root):
    from tkinter import messagebox

    if not is_admin():
        # The operator explicitly launches this separate IT command; Windows asks for elevation.
        if not getattr(sys, "frozen", False):
            messagebox.showerror("Feedback接続設定", "管理者として起動してください")
            return 1
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            "--feedback-admin",
            str(root),
            1,
        )
        return 0 if result > 32 else 1
    paths = DataPaths(root / "Data")
    for port in range(48150, 48181):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/operations/instance",
                timeout=0.3,
            ) as response:
                value = json.load(response)
            if value.get("instance_id") != instance_id(paths):
                continue
            token = issue(paths)
            webbrowser.open(f"http://127.0.0.1:{port}/feedback-admin#" + token)
            return 0
        except (OSError, ValueError):
            continue
    messagebox.showinfo("Feedback接続設定", "同じフォルダーのブンセン予測を先に起動してください。")
    return 1
