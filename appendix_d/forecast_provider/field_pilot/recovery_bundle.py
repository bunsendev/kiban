"""Field Pilotの許可済みファイルとPostgreSQL dumpを検証可能なZIPにまとめる。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

FORMAT = "bunsen-field-pilot-recovery-v1"
CONFIG_FILES = {
    "Config/pilot-settings.json": "config/pilot-settings.json",
    "Config/inbox-policy.json": "config/inbox-policy.json",
}
OPTIONAL_CONFIG_FILES = {
    "Config/recovery-policy.json": "config/recovery-policy.json",
    "Config/feedback-client.json": "config/feedback-client.json",
    "Config/feedback-server-public.pem": "config/feedback-server-public.pem",
    "Config/feedback-update-public.pem": "config/feedback-update-public.pem",
}
OPTIONAL_FILES = {
    "LocalSettings/field-settings.sqlite3": "settings/field-settings.sqlite3",
    "Inbox/inbox.sqlite3": "learning/inbox.sqlite3",
    "Inbox/improvement-events.sqlite3": "learning/improvement-events.sqlite3",
    "Inbox/feedback.sqlite3": "learning/feedback.sqlite3",
}
DB_FILE = "database/postgres.dump"
ALLOWED = (set(CONFIG_FILES.values()) | set(OPTIONAL_CONFIG_FILES.values())
           | set(OPTIONAL_FILES.values()) | {DB_FILE})
MAX_CONFIG_BYTES = 1_048_576
MAX_SQLITE_BYTES = 10 * 1024**3
MAX_DUMP_BYTES = 100 * 1024**3


def _app_version() -> str:
    try:
        return version("bunsen-forecast-provider")
    except PackageNotFoundError:
        return "unpackaged"


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _check_source(path: Path, *, sqlite: bool = False) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("RECOVERY_SOURCE_INVALID")
    if sqlite:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("RECOVERY_SQLITE_INVALID")


def create_bundle(data_root: Path, output: Path, *, mode: str,
                  postgres_dump: Path | None = None,
                  config_dir: Path | None = None, settings_dir: Path | None = None,
                  inbox_dir: Path | None = None,
                  release_fingerprint: str | None = None) -> dict:
    if mode not in {"FULL", "SETTINGS"}:
        raise ValueError("RECOVERY_MODE_INVALID")
    if data_root.is_symlink() or output.is_symlink() or output.parent.is_symlink():
        raise ValueError("RECOVERY_PATH_INVALID")
    if mode == "FULL" and postgres_dump is None:
        raise ValueError("RECOVERY_DATABASE_REQUIRED")
    if mode == "SETTINGS" and postgres_dump is not None:
        raise ValueError("RECOVERY_SETTINGS_MUST_EXCLUDE_DATABASE")
    config_root = config_dir or data_root / "Config"
    settings_root = settings_dir or data_root / "LocalSettings"
    inbox_root = inbox_dir or data_root / "Inbox"
    if any(path.is_symlink() for path in (config_root, settings_root, inbox_root)):
        raise ValueError("RECOVERY_PATH_INVALID")
    sources: dict[str, Path] = {}
    for relative, archive_name in CONFIG_FILES.items():
        source = config_root / Path(relative).name
        _check_source(source)
        if source.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError("RECOVERY_CONFIG_TOO_LARGE")
        sources[archive_name] = source
    for relative, archive_name in OPTIONAL_CONFIG_FILES.items():
        source = config_root / Path(relative).name
        if source.exists() or source.is_symlink():
            _check_source(source)
            if source.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError("RECOVERY_CONFIG_TOO_LARGE")
            sources[archive_name] = source
    for relative, archive_name in OPTIONAL_FILES.items():
        root = settings_root if relative.startswith("LocalSettings/") else inbox_root
        source = root / Path(relative).name
        if source.exists() or source.is_symlink():
            _check_source(source, sqlite=True)
            if source.stat().st_size > MAX_SQLITE_BYTES:
                raise ValueError("RECOVERY_SQLITE_TOO_LARGE")
            sources[archive_name] = source
    if postgres_dump is not None:
        _check_source(postgres_dump)
        with postgres_dump.open("rb") as stream:
            signature = stream.read(5)
        if not 0 < postgres_dump.stat().st_size <= MAX_DUMP_BYTES or signature != b"PGDMP":
            raise ValueError("RECOVERY_DUMP_INVALID")
        sources[DB_FILE] = postgres_dump
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    manifest = {
        "format": FORMAT, "mode": mode, "created_at": datetime.now(UTC).isoformat(),
        "application_version": _app_version(),
        "release_fingerprint": release_fingerprint, "files": {},
    }
    try:
        with tempfile.TemporaryDirectory(prefix=".recovery-sqlite-", dir=output.parent) as scratch:
            for archive_name, source in list(sources.items()):
                if archive_name in OPTIONAL_FILES.values():
                    snapshot = Path(scratch) / source.name
                    with closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro",
                                                 uri=True)) as original:
                        with closing(sqlite3.connect(snapshot)) as copy:
                            original.backup(copy)
                    _check_source(snapshot, sqlite=True)
                    if snapshot.stat().st_size > MAX_SQLITE_BYTES:
                        raise ValueError("RECOVERY_SQLITE_TOO_LARGE")
                    sources[archive_name] = snapshot
            with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
                for archive_name, source in sorted(sources.items()):
                    digest, size = _hash_file(source)
                    manifest["files"][archive_name] = {"sha256": digest, "size": size}
                    archive.write(source, archive_name,
                                  compress_type=zipfile.ZIP_STORED if archive_name == DB_FILE
                                  else zipfile.ZIP_DEFLATED)
                archive.writestr("manifest.json", json.dumps(
                    manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ))
        verify_bundle(temporary, release_fingerprint=release_fingerprint)
        os.replace(temporary, output)
        return manifest
    finally:
        temporary.unlink(missing_ok=True)


def verify_bundle(bundle: Path, *, release_fingerprint: str | None = None) -> dict:
    if bundle.is_symlink() or not bundle.is_file():
        raise ValueError("RECOVERY_BUNDLE_INVALID")
    with zipfile.ZipFile(bundle) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("RECOVERY_ARCHIVE_ENTRIES_INVALID")
        if set(names) - ALLOWED - {"manifest.json"}:
            raise ValueError("RECOVERY_ARCHIVE_ENTRIES_INVALID")
        for entry in entries:
            if (entry.is_dir() or stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK
                    or entry.filename.startswith("/") or ".." in Path(entry.filename).parts):
                raise ValueError("RECOVERY_ARCHIVE_ENTRIES_INVALID")
            limit = (MAX_CONFIG_BYTES if entry.filename.startswith("config/")
                     or entry.filename == "manifest.json" else MAX_DUMP_BYTES
                     if entry.filename == DB_FILE else MAX_SQLITE_BYTES)
            if entry.file_size > limit:
                raise ValueError("RECOVERY_ARCHIVE_TOO_LARGE")
        manifest = json.loads(archive.read("manifest.json"))
        if (not isinstance(manifest, dict) or manifest.get("format") != FORMAT
                or manifest.get("mode") not in {"FULL", "SETTINGS"}
                or not isinstance(manifest.get("files"), dict)
                or set(manifest["files"]) != set(names) - {"manifest.json"}
                or not set(CONFIG_FILES.values()).issubset(manifest["files"])
                or (DB_FILE in manifest["files"]) != (manifest["mode"] == "FULL")):
            raise ValueError("RECOVERY_MANIFEST_INVALID")
        current = _app_version()
        saved = manifest.get("application_version")
        if not isinstance(saved, str) or saved != current:
            raise ValueError("RECOVERY_VERSION_INCOMPATIBLE")
        if (release_fingerprint is not None
                and manifest.get("release_fingerprint") != release_fingerprint):
            raise ValueError("RECOVERY_RELEASE_INCOMPATIBLE")
        for entry in entries:
            if entry.filename == "manifest.json":
                continue
            expected = manifest["files"][entry.filename]
            if (not isinstance(expected, dict) or set(expected) != {"sha256", "size"}
                    or not isinstance(expected["size"], int)
                    or expected["size"] != entry.file_size):
                raise ValueError("RECOVERY_MANIFEST_INVALID")
            digest = hashlib.sha256()
            with archive.open(entry) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected["sha256"]:
                raise ValueError("RECOVERY_HASH_MISMATCH")
        return manifest


def stage_bundle(bundle: Path, destination: Path, *,
                 release_fingerprint: str | None = None) -> dict:
    manifest = verify_bundle(bundle, release_fingerprint=release_fingerprint)
    if destination.exists() or destination.is_symlink() or destination.parent.is_symlink():
        raise ValueError("RECOVERY_STAGE_PATH_INVALID")
    destination.mkdir(parents=True)
    with zipfile.ZipFile(bundle) as archive:
        for name in manifest["files"]:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
    for name, expected in manifest["files"].items():
        if _hash_file(destination / name) != (expected["sha256"], expected["size"]):
            raise ValueError("RECOVERY_STAGE_HASH_MISMATCH")
    for name in ("settings/field-settings.sqlite3", "learning/inbox.sqlite3",
                 "learning/improvement-events.sqlite3", "learning/feedback.sqlite3"):
        if name in manifest["files"]:
            _check_source(destination / name, sqlite=True)
    settings = json.loads((destination / "config/pilot-settings.json").read_text(encoding="utf-8"))
    if (not isinstance(settings, dict) or settings.get("mode") != "SHADOW"
            or settings.get("read_only") is not True):
        raise ValueError("RECOVERY_SETTINGS_INVALID")
    inbox = json.loads((destination / "config/inbox-policy.json").read_text(encoding="utf-8"))
    if not isinstance(inbox, dict) or not isinstance(inbox.get("required"), list):
        raise ValueError("RECOVERY_INBOX_POLICY_INVALID")
    if "config/recovery-policy.json" in manifest["files"]:
        policy = json.loads((destination / "config/recovery-policy.json").read_text(
            encoding="utf-8",
        ))
        if not isinstance(policy, dict) or any(
            not isinstance(policy.get(key), int) or not 1 <= policy[key] <= 365
            for key in ("daily_keep", "manual_keep", "pre_restore_keep")
        ):
            raise ValueError("RECOVERY_POLICY_INVALID")
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Field Pilot recovery bundle")
    actions = parser.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create")
    create.add_argument("--data-root", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--mode", choices=["FULL", "SETTINGS"], required=True)
    create.add_argument("--postgres-dump", type=Path)
    create.add_argument("--config-dir", type=Path)
    create.add_argument("--settings-dir", type=Path)
    create.add_argument("--inbox-dir", type=Path)
    create.add_argument("--release-fingerprint")
    verify = actions.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--release-fingerprint")
    stage = actions.add_parser("stage")
    stage.add_argument("--bundle", type=Path, required=True)
    stage.add_argument("--destination", type=Path, required=True)
    stage.add_argument("--release-fingerprint")
    arguments = parser.parse_args()
    if arguments.action == "create":
        result = create_bundle(arguments.data_root, arguments.output,
                               mode=arguments.mode, postgres_dump=arguments.postgres_dump,
                               config_dir=arguments.config_dir,
                               settings_dir=arguments.settings_dir,
                               inbox_dir=arguments.inbox_dir,
                               release_fingerprint=arguments.release_fingerprint)
    elif arguments.action == "verify":
        result = verify_bundle(arguments.bundle,
                               release_fingerprint=arguments.release_fingerprint)
    else:
        result = stage_bundle(arguments.bundle, arguments.destination,
                              release_fingerprint=arguments.release_fingerprint)
    print(json.dumps({"status": "OK", "mode": result["mode"],
                      "file_count": len(result["files"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
