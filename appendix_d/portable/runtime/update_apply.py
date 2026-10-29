"""Out-of-process update transaction: stopped app, backup, smoke, swap, rollback."""

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from pathlib import Path

from portable import APP_VERSION
from portable.runtime.local_http import request_json
from portable.runtime.release_update import TRUST_KEY, unpack, verified, version
from portable.runtime.update_state import write_state as atomic_json


def wait_parent(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        return
    try:
        if kernel.WaitForSingleObject(handle, 120000) != 0:
            raise ValueError("旧アプリの終了を確認できません")
    finally:
        kernel.CloseHandle(handle)


def backup_data(data, destination):
    files = []
    for path in data.rglob("*"):
        if path.is_symlink():
            raise ValueError("業務データのリンクはバックアップ対象外です")
        if path.is_file():
            files.append(path)
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(data).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("バックアップを検証できません")
        for path in files:
            if (
                hashlib.sha256(archive.read(path.relative_to(data).as_posix())).digest()
                != hashlib.sha256(path.read_bytes()).digest()
            ):
                raise ValueError("バックアップ中にデータが変更されました")


def smoke(executable, data, expected_version):
    from portable.launcher.main import available_ports

    port = next(available_ports())
    process = subprocess.Popen(
        [str(executable), "--server", "--port", str(port), "--data-root", str(data)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PORTABLE_SMOKE": "1"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                value = request_json(port, "/ready", timeout=2)
                if value.get("ready") and value.get("version") == expected_version:
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.25)
        raise ValueError("更新後の起動確認に失敗しました")
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=15)


def apply(root, stage_name, *, public_key=TRUST_KEY, smoke_test=smoke):
    root = Path(root).resolve()
    if not (root / "App/BunsenPortable.exe").is_file():
        raise ValueError("インストール先を確認できません")
    if not re.fullmatch("staged-[0-9a-f]{32}", stage_name):
        raise ValueError("更新フォルダーが不正です")
    work = root / "Updates"
    stage = work / stage_name
    offer = json.loads((stage / "offer.json").read_text("utf-8"))
    manifest = verified(offer["raw"].encode(), offer["signature"].encode(), public_key.read_bytes())
    if version(manifest["version"]) <= version(APP_VERSION):
        raise ValueError("古い版への更新はできません")
    archive = stage / "package.zip"
    if (
        archive.stat().st_size != manifest["size_bytes"]
        or hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["sha256"]
    ):
        raise ValueError("更新ファイルが変更されました")
    transaction = work / ("apply-" + uuid.uuid4().hex)
    transaction.mkdir()
    unpack(archive, transaction / "new", manifest)
    data = root / "Data"
    data.mkdir(exist_ok=True)
    backup = transaction / "Data-backup.zip"
    backup_data(data, backup)
    with zipfile.ZipFile(backup) as z:
        z.extractall(transaction / "smoke-data")
    new_app = transaction / "new/App"
    smoke_test(new_app / "BunsenPortable.exe", transaction / "smoke-data", manifest["version"])
    old_app = transaction / "old-App"
    changed = False
    replaced = []
    try:
        os.replace(root / "App", old_app)
        changed = True
        os.replace(new_app, root / "App")
        smoke_test(root / "App/BunsenPortable.exe", data, manifest["version"])
        # Keep launcher instructions and package identity in step with the application.
        for item in (transaction / "new").iterdir():
            if item.name == "App":
                continue
            destination = root / item.name
            previous = transaction / "old-files" / item.name
            previous.parent.mkdir(exist_ok=True)
            existed = destination.exists()
            if existed:
                os.replace(destination, previous)
            replaced.append((destination, previous, existed))
            os.replace(item, destination)
    except Exception:
        for destination, previous, existed in reversed(replaced):
            if destination.exists():
                failed = transaction / ("failed-" + destination.name)
                os.replace(destination, failed)
            if existed:
                os.replace(previous, destination)
        if changed:
            if (root / "App").exists():
                os.replace(root / "App", transaction / "failed-App")
            os.replace(old_app, root / "App")
            os.replace(data, transaction / "failed-Data")
            with zipfile.ZipFile(backup) as z:
                z.extractall(data)
        atomic_json(work / "status.json", {"status": "ROLLED_BACK", "backup": str(backup)})
        atomic_json(work / "last-apply.json", {"status": "ROLLED_BACK"})
        raise
    atomic_json(
        work / "status.json",
        {"status": "UPDATED", "version": manifest["version"], "backup": str(backup)},
    )
    atomic_json(work / "last-apply.json", {"status": "UPDATED", "version": manifest["version"]})


def run(root, stage, parent_pid):
    root = Path(root)
    try:
        wait_parent(parent_pid)
        apply(root, stage)
    except Exception:
        path = root / "Updates/status.json"
        value = json.loads(path.read_text("utf-8")) if path.exists() else {}
        if value.get("status") != "ROLLED_BACK":
            atomic_json(path, {"status": "APPLY_FAILED"})
            atomic_json(root / "Updates/last-apply.json", {"status": "APPLY_FAILED"})
    # Both success and rollback return the user to a usable launcher.
    subprocess.Popen(
        [str(root / "App/BunsenPortable.exe")],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def spawn_helper(root, stage):
    root = Path(root)
    helper = root / "Updates" / ("helper-" + uuid.uuid4().hex)
    shutil.copytree(root / "App", helper)
    return subprocess.Popen(
        [
            str(helper / "BunsenPortable.exe"),
            "--apply-update",
            str(root),
            "--stage",
            stage,
            "--parent-pid",
            str(os.getpid()),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
