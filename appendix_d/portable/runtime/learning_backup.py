"""Portable learning backup and startup-only, journaled directory restoration."""

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import uuid
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from portable import APP_VERSION

FORMAT = "bunsen-learning-backup-v1"
LIMIT = 256 * 1024 * 1024
EXPANDED_LIMIT = 2 * 1024 * 1024 * 1024
ROOTS = {
    "State",
    "Input",
    "Incoming",
    "Results",
    "Analysis",
    "Prepared",
    "Decisions",
    "FormalInventory",
    "FormalForecast",
    "Inbox",
    "Logs",
}
LOCAL = {
    "installation.json",
    "delivery-config.json",
    "delivery-outbox.sqlite3",
    "feedback-admin-session.json",
    "feedback-connection.json",
}


def atomic(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def identity_uri(path):
    # pathlib treats Win32's extended namespace as a URI authority ("%3F").
    value = str(path)
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value).as_uri() + "?mode=ro"


def readonly_uri(path):
    # Percent-encode the Win32 namespace as a filename, not a URI authority.
    # This keeps read-only SQLite access working beyond MAX_PATH as well.
    return "file:" + quote(str(path), safe="/") + "?mode=ro"


def local_only(name):
    p = PurePosixPath(name)
    return p.name in LOCAL or p.suffix.lower() == ".dpapi" or p.name.endswith(("-wal", "-shm"))


def safe_name(name):
    p = PurePosixPath(name)
    if (
        p.as_posix() != name
        or any(
            v.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *("COM" + str(i) for i in range(1, 10)),
                *("LPT" + str(i) for i in range(1, 10)),
            }
            for v in p.parts
        )
        or not p.parts
        or p.parts[0] not in ROOTS
        or "\\" in name
        or ":" in name
        or ".." in p.parts
        or p.is_absolute()
        or "\x00" in name
        or any(v.endswith((" ", ".")) for v in p.parts)
    ):
        raise ValueError("バックアップに不正なパスがあります")
    return p


def check_db(path):
    if path.suffix.lower() in {".sqlite3", ".sqlite", ".db"}:
        with closing(sqlite3.connect(readonly_uri(path), uri=True)) as db:
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise ValueError("バックアップ内のDBが破損しています")


class LearningBackup:
    def __init__(self, data_root):
        self.data = Path(data_root).resolve()
        # Kept outside Data so restoring Data cannot erase rollback or journal.
        ident = hashlib.sha256(identity_uri(self.data).casefold().encode()).hexdigest()[:16]
        self.work = self.data.parent / ("BunsenRecovery-" + ident)
        self.work.mkdir(parents=True, exist_ok=True)

    def status(self):
        p = self.work / "status.json"
        result = json.loads(p.read_text("utf-8")) if p.exists() else {"status": "NOT_RESTORED"}
        return result | {
            "pending": (self.work / "pending.json").exists(),
            "recovery_folder": str(self.work),
        }

    def create(self):
        target = self.work / ("learning-" + uuid.uuid4().hex + ".zip")
        files = {}
        with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(self.data.rglob("*")):
                if p.is_symlink() or p.is_junction():
                    raise ValueError("リンクを含むデータはバックアップできません")
                if not p.is_file():
                    continue
                name = p.relative_to(self.data).as_posix()
                if local_only(name):
                    continue
                safe_name(name)
                if p.suffix.lower() in {".sqlite3", ".sqlite", ".db"}:
                    copy = self.work / (uuid.uuid4().hex + ".sqlite3")
                    try:
                        with closing(sqlite3.connect(readonly_uri(p), uri=True)) as src:
                            with closing(sqlite3.connect(copy)) as dest:
                                src.backup(dest)
                        check_db(copy)
                        files[name] = digest(copy)
                        z.write(copy, name)
                    finally:
                        copy.unlink(missing_ok=True)
                else:
                    before = digest(p)
                    z.write(p, name)
                    if digest(p) != before:
                        raise ValueError(
                            "バックアップ中にファイルが変わりました。再試行してください"
                        )
                    files[name] = before
            if not files:
                raise ValueError("バックアップする学習・業務データがありません")
            current = {
                p.relative_to(self.data).as_posix()
                for p in self.data.rglob("*")
                if p.is_file() and not local_only(p.relative_to(self.data).as_posix())
            }
            if current != set(files):
                raise ValueError("バックアップ中にファイルが増減しました。再試行してください")
            for name, sha in files.items():
                if PurePosixPath(name).suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
                    if digest(self.data / name) != sha:
                        raise ValueError("バックアップ中にファイルが変わりました")
            z.writestr(
                "backup-manifest.json",
                json.dumps(
                    {
                        "format": FORMAT,
                        "app_version": APP_VERSION,
                        "source_data_root": str(self.data),
                        "created_at": datetime.now(UTC).isoformat(),
                        "files": files,
                    },
                    ensure_ascii=False,
                ),
            )
        self.inspect(target)
        return target

    def inspect(self, archive):
        if archive.stat().st_size > LIMIT:
            raise ValueError("バックアップZIPは256 MiB以下にしてください")
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if len(members) > 100000 or sum(m.file_size for m in members) > EXPANDED_LIMIT:
                raise ValueError("バックアップの展開サイズが上限を超えています")
            names = [m.filename for m in members]
            if len({n.casefold() for n in names}) != len(names):
                raise ValueError("バックアップのファイル名が重複しています")
            manifest = None
            if "backup-manifest.json" in names:
                if z.getinfo("backup-manifest.json").file_size > 16 * 1024 * 1024:
                    raise ValueError("バックアップ情報が大きすぎます")
                manifest = json.loads(z.read("backup-manifest.json"))
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("format") != FORMAT
                    or not isinstance(manifest.get("files"), dict)
                    or not isinstance(manifest.get("app_version"), str)
                ):
                    raise ValueError("対応する学習バックアップではありません")
                from portable.runtime.release_update import version

                if version(manifest["app_version"]) > version(APP_VERSION):
                    raise ValueError("新しい版のバックアップです。先にアプリを更新してください")
            prefix = "Data/" if not manifest and any(n.startswith("Data/") for n in names) else ""
            accepted = []
            accepted_names = set()
            for m in members:
                if m.filename == "backup-manifest.json" or m.is_dir():
                    continue
                if stat.S_ISLNK(m.external_attr >> 16) or m.flag_bits & 1:
                    raise ValueError("リンク・暗号化ZIPは復元できません")
                name = m.filename.removeprefix(prefix)
                safe_name(name)
                if name.casefold() in accepted_names:
                    raise ValueError("復元先のファイル名が重複しています")
                accepted_names.add(name.casefold())
                if local_only(name):
                    continue
                if manifest and manifest["files"].get(name) is None:
                    raise ValueError("バックアップ一覧にないファイルがあります")
                h = hashlib.sha256()
                with z.open(m) as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(chunk)
                if manifest and h.hexdigest() != manifest["files"][name]:
                    raise ValueError("バックアップのハッシュが一致しません")
                accepted.append((m.filename, name))
            if not accepted or (manifest and set(manifest["files"]) != {n for _, n in accepted}):
                raise ValueError("バックアップが空、またはファイルが不足しています")
            return {
                "legacy": manifest is None,
                "files": len(accepted),
                "entries": accepted,
                "created_at": None if manifest is None else manifest.get("created_at"),
                "version": None if manifest is None else manifest["app_version"],
                "sha256": digest(archive),
            }

    def stage(self, archive, *, confirm, allow_legacy=False):
        info = self.inspect(archive)
        if not confirm or (info["legacy"] and not allow_legacy):
            raise ValueError("置換復元と、旧形式の場合はハッシュ未提供の確認が必要です")
        if (self.work / "pending.json").exists():
            raise ValueError("既に復元を予約しています。取消または再起動してください")
        target = self.work / ("restore-" + uuid.uuid4().hex + ".zip")
        shutil.copyfile(archive, target)
        atomic(self.work / "pending.json", {"archive": target.name, "sha256": info["sha256"]})
        return {"status": "RESTART_REQUIRED", "files": info["files"]}

    def cancel(self):
        (self.work / "pending.json").unlink(missing_ok=True)

    def apply_pending(self, validate=None):
        """Called before any DB/store/watch thread opens, never by a live API."""
        journal = self.work / "swap.json"
        pending = self.work / "pending.json"
        if journal.exists():
            txid = json.loads(journal.read_text("utf-8"))["transaction"]
            uuid.UUID(txid)
            old = self.work / txid / "previous-Data"
            if old.exists():
                new = self.work / txid / "new-Data"
                if not self.data.exists() or new.exists():
                    if self.data.exists():
                        self.data.rename(self.work / txid / ("interrupted-" + uuid.uuid4().hex))
                    old.rename(self.data)
                    state = "INTERRUPTED_ROLLED_BACK"
                else:
                    state = "RESTORED"
                atomic(self.work / "status.json", {"status": state, "previous_data": str(old)})
                pending.unlink(missing_ok=True)
            journal.unlink()
        if not pending.exists():
            return self.status()
        tx = self.work / str(uuid.uuid4())
        tx.mkdir()
        new = tx / "new-Data"
        new.mkdir()
        old = tx / "previous-Data"
        try:
            value = json.loads(pending.read_text("utf-8"))
            if Path(value["archive"]).name != value["archive"]:
                raise ValueError("復元予約が不正です")
            archive = self.work / value["archive"]
            info = self.inspect(archive)
            if info["sha256"] != value["sha256"]:
                raise ValueError("予約後にバックアップが変更されました")
            with zipfile.ZipFile(archive) as z:
                for member, name in info["entries"]:
                    dest = new / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, dest.open("xb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                    check_db(dest)
            # Retain this target PC's identity/config, never a previous device's.
            for name in LOCAL:
                p = self.data / "State" / name
                if p.is_file():
                    dest = new / "State" / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if p.suffix.lower() == ".sqlite3":
                        with closing(sqlite3.connect(p)) as src:
                            with closing(sqlite3.connect(dest)) as dst:
                                src.backup(dst)
                    else:
                        shutil.copyfile(p, dest)
            if validate is not None:
                try:
                    validate(new)
                except Exception as exc:
                    raise ValueError("復元候補のアプリ初期化を確認できません: " + str(exc)) from exc
            atomic(journal, {"transaction": tx.name})
            if self.data.exists():
                self.data.rename(old)
            try:
                new.rename(self.data)
            except OSError:
                if old.exists():
                    old.rename(self.data)
                raise
            atomic(
                self.work / "status.json",
                {"status": "RESTORED", "previous_data": str(old), "files": info["files"]},
            )
        except (ValueError, OSError, sqlite3.DatabaseError, zipfile.BadZipFile, KeyError) as exc:
            atomic(self.work / "status.json", {"status": "FAILED", "error": str(exc)})
            if old.exists() and not self.data.exists():
                # Do not let normal initialization silently create an empty Data.
                # Preserve the journal and retry rollback on the next process start.
                raise OSError(
                    "元データの復帰待ちです。復旧用フォルダを残して再起動してください"
                ) from exc
        pending.unlink(missing_ok=True)
        journal.unlink(missing_ok=True)
        return self.status()
