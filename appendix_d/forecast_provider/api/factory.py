"""ASGI server用factory。"""

import os
from pathlib import Path

from ..acceptance import PostgresAcceptanceStore
from ..catalog import PostgresCatalogStore
from ..daily import PostgresDailyStore
from ..evaluation_registry import PostgresEvaluationRegistryStore
from ..ingestion import PostgresIngestionStore
from ..jobs import PostgresRunStore
from ..master import PostgresMasterStore
from ..normalization import PostgresNormalizationStore
from ..reporting import PostgresReportingStore
from ..selection import PostgresSelectionStore
from .app import create_app


def from_environment():
    dsn = os.environ.get("KIBAN_POSTGRES_DSN")
    token = os.environ.get("KIBAN_API_TOKEN")
    root = os.environ.get("KIBAN_SNAPSHOT_ROOT")
    report_root = os.environ.get("KIBAN_REPORT_ROOT")
    if not dsn or not token or not root or not report_root:
        raise RuntimeError(
            "KIBAN_POSTGRES_DSN、KIBAN_API_TOKEN、KIBAN_SNAPSHOT_ROOT、"
            "KIBAN_REPORT_ROOTを設定してください"
        )
    return create_app(
        PostgresRunStore(dsn),
        PostgresCatalogStore(dsn),
        token,
        Path(root),
        PostgresIngestionStore(dsn),
        PostgresNormalizationStore(dsn),
        PostgresMasterStore(dsn),
        PostgresDailyStore(dsn),
        PostgresAcceptanceStore(dsn),
        PostgresSelectionStore(dsn),
        PostgresEvaluationRegistryStore(dsn),
        PostgresReportingStore(dsn),
        Path(report_root),
    )
