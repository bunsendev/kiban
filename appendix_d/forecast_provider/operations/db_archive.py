"""PostgreSQL custom archiveの作成、検証、復元。"""

import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

SCHEMA_VERSION = "kiban-postgres-backup/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_QUERY_ENV = {
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "channel_binding": "PGCHANNELBINDING",
    "connect_timeout": "PGCONNECT_TIMEOUT",
}


@dataclass(frozen=True)
class ConnectionSettings:
    database: str
    environment: dict[str, str]


def connection_settings(dsn: str) -> ConnectionSettings:
    parsed = urlsplit(dsn)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not parsed.hostname
        or parsed.fragment
    ):
        raise ValueError("PostgreSQL DSNはhostを含むpostgresql URIです")
    database = unquote(parsed.path.removeprefix("/"))
    if (
        not database
        or len(database) > 200
        or "/" in database
        or any(ord(character) < 32 for character in database)
    ):
        raise ValueError("PostgreSQL DSNのdatabase名が不正です")
    query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
    unknown = set(query) - set(_QUERY_ENV)
    if unknown or any(len(values) != 1 or not values[0] for values in query.values()):
        raise ValueError("PostgreSQL DSNに未対応または重複queryがあります")
    environment = {
        "PGHOST": parsed.hostname,
        "PGDATABASE": database,
        "PGCONNECT_TIMEOUT": "5",
    }
    if parsed.port:
        environment["PGPORT"] = str(parsed.port)
    if parsed.username:
        environment["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        environment["PGPASSWORD"] = unquote(parsed.password)
    for name, values in query.items():
        environment[_QUERY_ENV[name]] = values[0]
    if any(
        any(ord(character) < 32 for character in value)
        for value in environment.values()
    ):
        raise ValueError("PostgreSQL DSNに制御文字は使えません")
    return ConnectionSettings(database, environment)


def _run(command: list[str], environment: dict[str, str] | None = None) -> str:
    process_environment = postgres_environment(environment)
    result = subprocess.run(
        command,
        env=process_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name}の実行に失敗しました")
    return result.stdout.strip()


def postgres_environment(environment: dict[str, str] | None = None) -> dict[str, str]:
    """OS環境のPostgreSQL接続値を混ぜずに実行環境を作る。"""

    process_environment = os.environ.copy()
    if environment is not None:
        for name in {
            "PGHOST",
            "PGPORT",
            "PGDATABASE",
            "PGUSER",
            "PGPASSWORD",
            *_QUERY_ENV.values(),
        }:
            process_environment.pop(name, None)
    process_environment.update(environment or {})
    return process_environment


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            temporary = Path(stream.name)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def backup_database(dsn: str, output_dir: Path) -> Path:
    connection = connection_settings(dsn)
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=".kiban-postgres-", suffix=".dump", dir=destination
    )
    os.close(handle)
    temporary = Path(temporary_name)
    archive = None
    try:
        _run(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                f"--file={temporary}",
            ],
            connection.environment,
        )
        if temporary.stat().st_size <= 0:
            raise RuntimeError("pg_dumpが空のarchiveを生成しました")
        digest = _sha256(temporary)
        created_at = datetime.now(UTC)
        basename = (
            f"kiban-{created_at.strftime('%Y%m%dT%H%M%SZ')}-"
            f"{digest[:12]}-{uuid.uuid4().hex[:8]}"
        )
        archive = destination / f"{basename}.dump"
        manifest = destination / f"{basename}.manifest.json"
        if archive.exists() or manifest.exists():
            raise RuntimeError("backup出力名が重複しました")
        temporary.replace(archive)
        _write_json_atomic(
            manifest,
            {
                "archive": archive.name,
                "created_at": created_at.isoformat().replace("+00:00", "Z"),
                "database": connection.database,
                "pg_dump_version": _run(["pg_dump", "--version"]),
                "schema_version": SCHEMA_VERSION,
                "sha256": digest,
                "size_bytes": archive.stat().st_size,
            },
        )
        return manifest
    except Exception:
        if archive is not None:
            archive.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def _verified_archive(manifest_path: Path) -> tuple[Path, dict]:
    manifest_path = manifest_path.resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("backup manifestを読込めません") from exc
    expected_fields = {
        "archive",
        "created_at",
        "database",
        "pg_dump_version",
        "schema_version",
        "sha256",
        "size_bytes",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_fields:
        raise ValueError("backup manifestの項目が不正です")
    archive_name = manifest["archive"]
    if not isinstance(archive_name, str) or Path(archive_name).name != archive_name:
        raise ValueError("backup archive名が不正です")
    archive = (manifest_path.parent / archive_name).resolve()
    if archive.parent != manifest_path.parent or not archive.is_file():
        raise ValueError("backup archiveがmanifestと同じdirectoryにありません")
    digest = manifest["sha256"]
    size = manifest["size_bytes"]
    if (
        manifest["schema_version"] != SCHEMA_VERSION
        or not isinstance(digest, str)
        or not _SHA256.fullmatch(digest)
        or not isinstance(size, int)
        or size <= 0
    ):
        raise ValueError("backup manifestの値が不正です")
    for name in ("created_at", "database", "pg_dump_version"):
        if not isinstance(manifest[name], str) or not manifest[name]:
            raise ValueError("backup manifestの値が不正です")
    actual_digest = _sha256(archive)
    if archive.stat().st_size != size or not secrets.compare_digest(actual_digest, digest):
        raise ValueError("backup archiveのchecksumが一致しません")
    return archive, manifest


def verify_backup(manifest_path: Path) -> dict:
    archive, manifest = _verified_archive(manifest_path)
    _run(["pg_restore", "--list", str(archive)])
    return manifest


def restore_database(dsn: str, manifest_path: Path, confirm_database: str) -> None:
    connection = connection_settings(dsn)
    if not secrets.compare_digest(connection.database, confirm_database):
        raise ValueError("確認用database名が復元先と一致しません")
    archive, _manifest = _verified_archive(manifest_path)
    _run(["pg_restore", "--list", str(archive)])
    restore_archive(connection, archive, clean=True)


def restore_archive(
    connection: ConnectionSettings, archive: Path, *, clean: bool = False
) -> None:
    """検証済みarchiveを指定接続先へ復元する。

    呼出元は必ず``_verified_archive``を通したPathだけを渡す。
    """

    command = [
        "pg_restore",
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
        "--single-transaction",
    ]
    if clean:
        command.extend(["--clean", "--if-exists"])
    command.extend([f"--dbname={connection.database}", str(archive)])
    _run(
        command,
        connection.environment,
    )
