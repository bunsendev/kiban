"""Phase 1Xから1Kまでに必要なPostgreSQL schemaと権限の検査。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .contracts import REQUIRED_RELATIONS

Connect = Callable[..., Any]


def _default_connect(dsn: str):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("PostgreSQL検査にはpsycopgが必要です") from exc
    return psycopg.connect(dsn, connect_timeout=5)


def inspect_database(dsn: str, *, connect: Connect = _default_connect) -> dict:
    """DSNやdatabase/user名を返さず、必要な技術情報だけを返す。"""
    try:
        with connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version_num')::integer")
            server_major = int(cursor.fetchone()[0]) // 10_000
            cursor.execute(
                """
                SELECT table_name
                  FROM information_schema.tables
                 WHERE table_schema = 'public'
                   AND table_name = ANY(%s)
                """,
                (list(REQUIRED_RELATIONS),),
            )
            present = {row[0] for row in cursor.fetchall()}
            insufficient = []
            for relation in sorted(present):
                cursor.execute(
                    """
                    SELECT has_table_privilege(current_user, %s, 'SELECT')
                       AND has_table_privilege(current_user, %s, 'INSERT')
                       AND has_table_privilege(current_user, %s, 'UPDATE')
                    """,
                    (f"public.{relation}",) * 3,
                )
                if not cursor.fetchone()[0]:
                    insufficient.append(relation)
        return {
            "reachable": True,
            "server_major": server_major,
            "required_relation_count": len(REQUIRED_RELATIONS),
            "present_relation_count": len(present),
            "missing_relations": sorted(set(REQUIRED_RELATIONS) - present),
            "insufficient_privileges": insufficient,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "server_major": None,
            "required_relation_count": len(REQUIRED_RELATIONS),
            "present_relation_count": 0,
            "missing_relations": [],
            "insufficient_privileges": [],
            "failure_class": type(exc).__name__,
        }
