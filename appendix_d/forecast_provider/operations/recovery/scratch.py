"""内部生成した隔離DBの作成・復元・破棄。"""

import re
import secrets
import uuid
from dataclasses import replace
from pathlib import Path

from ..db_archive import ConnectionSettings, _run, restore_archive

_SCRATCH_NAME = re.compile(r"^kiban_drill_[0-9a-f]{12}$")


def generate_scratch_name() -> str:
    return f"kiban_drill_{uuid.uuid4().hex[:12]}"


def scratch_connection(source: ConnectionSettings, name: str) -> ConnectionSettings:
    if not _SCRATCH_NAME.fullmatch(name):
        raise ValueError("隔離database名が内部生成形式ではありません")
    if secrets.compare_digest(source.database, name):
        raise ValueError("隔離databaseと復元元databaseは分離が必要です")
    environment = dict(source.environment)
    environment["PGDATABASE"] = name
    return replace(source, database=name, environment=environment)


def create_scratch(source: ConnectionSettings, target: ConnectionSettings) -> None:
    scratch_connection(source, target.database)
    environment = dict(source.environment)
    environment["PGDATABASE"] = "postgres"
    _run(
        [
            "createdb",
            "--maintenance-db=postgres",
            "--template=template0",
            "--encoding=UTF8",
            target.database,
        ],
        environment,
    )


def restore_scratch(target: ConnectionSettings, archive: Path) -> None:
    restore_archive(target, archive, clean=False)


def drop_scratch(source: ConnectionSettings, target: ConnectionSettings) -> None:
    scratch_connection(source, target.database)
    environment = dict(source.environment)
    environment["PGDATABASE"] = "postgres"
    _run(
        [
            "dropdb",
            "--if-exists",
            "--force",
            "--maintenance-db=postgres",
            target.database,
        ],
        environment,
    )
