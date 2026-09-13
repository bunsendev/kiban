"""DB名や行値を保存せずPostgreSQL public schemaを照合する。"""

import hashlib
import re
import subprocess

from ..db_archive import ConnectionSettings, postgres_environment
from .contracts import DatabaseFingerprint

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_SQL = r"""
COPY (
  SELECT json_build_array('column', table_name, column_name, ordinal_position,
      data_type, udt_schema, udt_name, is_nullable, column_default,
      character_maximum_length, numeric_precision, numeric_scale,
      datetime_precision, identity_generation, is_generated)::text
  FROM information_schema.columns WHERE table_schema = 'public'
  UNION ALL
  SELECT json_build_array('constraint', c.relname, x.conname,
      pg_get_constraintdef(x.oid, true))::text
  FROM pg_catalog.pg_constraint x
  JOIN pg_catalog.pg_class c ON c.oid = x.conrelid
  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public'
  UNION ALL
  SELECT json_build_array('index', tablename, indexname, indexdef)::text
  FROM pg_catalog.pg_indexes WHERE schemaname = 'public'
  UNION ALL
  SELECT json_build_array('sequence', sequencename, data_type, start_value,
      min_value, max_value, increment_by, cycle, cache_size, last_value)::text
  FROM pg_catalog.pg_sequences WHERE schemaname = 'public'
  UNION ALL
  SELECT json_build_array('view', viewname, definition)::text
  FROM pg_catalog.pg_views WHERE schemaname = 'public'
  ORDER BY 1
) TO STDOUT;
"""
_TABLES_SQL = """
COPY (
  SELECT tablename FROM pg_catalog.pg_tables
  WHERE schemaname = 'public' ORDER BY tablename COLLATE "C"
) TO STDOUT;
"""


def _psql_command(sql: str) -> list[str]:
    return [
        "psql",
        "--no-psqlrc",
        "--quiet",
        "--tuples-only",
        "--no-align",
        "--set=ON_ERROR_STOP=1",
        "--command",
        sql,
    ]


def _psql_bytes(connection: ConnectionSettings, sql: str) -> bytes:
    result = subprocess.run(
        _psql_command(sql),
        env=postgres_environment(connection.environment),
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("psqlの実行に失敗しました")
    return result.stdout


def _psql_sha256(connection: ConnectionSettings, sql: str) -> str:
    """psqlの出力をmemoryに保持せずstreamingで照合値にする。"""

    digest = hashlib.sha256()
    with subprocess.Popen(
        _psql_command(sql),
        env=postgres_environment(connection.environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        if process.stdout is None:
            raise RuntimeError("psqlの出力を取得できません")
        for block in iter(lambda: process.stdout.read(1024 * 1024), b""):
            digest.update(block)
        if process.wait():
            raise RuntimeError("psqlの実行に失敗しました")
    return digest.hexdigest()


def _quoted_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("PostgreSQL relation名が不正です")
    return '"' + value.replace('"', '""') + '"'


def database_fingerprint(connection: ConnectionSettings) -> DatabaseFingerprint:
    """schema定義と各tableの決定的な行JSONをstreaming SHA-256にする。"""

    version = _psql_bytes(connection, "SHOW server_version_num;").decode("ascii").strip()
    if not version.isdigit():
        raise RuntimeError("PostgreSQL versionを取得できません")
    tables = _psql_bytes(connection, _TABLES_SQL).decode("utf-8").splitlines()
    schema_digest = _psql_sha256(connection, _SCHEMA_SQL)
    digest = hashlib.sha256()
    digest.update(f"schema:{schema_digest}\n".encode())
    for table in tables:
        identifier = _quoted_identifier(table)
        table_digest = _psql_sha256(
            connection,
            "COPY (SELECT row_to_json(t)::text "
            f"FROM public.{identifier} AS t "
            'ORDER BY (row_to_json(t)::text) COLLATE "C") TO STDOUT;',
        )
        if not _SHA256.fullmatch(table_digest):
            raise RuntimeError("relation fingerprintを作成できません")
        digest.update(table.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(table_digest.encode("ascii"))
        digest.update(b"\n")
    return DatabaseFingerprint(
        sha256=digest.hexdigest(),
        relation_count=len(tables),
        postgres_major=int(version) // 10_000,
    )
