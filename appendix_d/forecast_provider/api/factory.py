"""ASGI server用factory。"""

import os

from ..jobs import PostgresRunStore
from .app import create_app


def from_environment():
    dsn = os.environ.get("KIBAN_POSTGRES_DSN")
    token = os.environ.get("KIBAN_API_TOKEN")
    if not dsn or not token:
        raise RuntimeError("KIBAN_POSTGRES_DSNとKIBAN_API_TOKENを設定してください")
    return create_app(PostgresRunStore(dsn), token)
