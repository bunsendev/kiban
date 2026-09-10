"""ASGI server用factory。"""

import os
from collections.abc import Mapping
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
from .security import SecuritySettings, TokenAuthenticator


def load_api_security(
    environment: Mapping[str, str],
) -> tuple[TokenAuthenticator, SecuritySettings]:
    token = environment.get("KIBAN_API_TOKEN")
    credentials_json = environment.get("KIBAN_API_CREDENTIALS")
    deployment_mode = environment.get("KIBAN_DEPLOYMENT_MODE", "development")
    allowed_hosts = tuple(
        dict.fromkeys(
            value.strip()
            for value in environment.get("KIBAN_ALLOWED_HOSTS", "").split(",")
            if value.strip()
        )
    )
    if token and credentials_json:
        raise RuntimeError("KIBAN_API_TOKENとKIBAN_API_CREDENTIALSは同時に設定できません")
    if deployment_mode == "production" and token:
        raise RuntimeError("productionではKIBAN_API_CREDENTIALSを使用してください")
    if credentials_json:
        try:
            authenticator = TokenAuthenticator.from_json(credentials_json)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
    elif token:
        authenticator = TokenAuthenticator.single(
            token,
            environment.get("KIBAN_API_SUBJECT", "local-admin"),
        )
    else:
        raise RuntimeError("KIBAN_API_CREDENTIALSまたはKIBAN_API_TOKENを設定してください")
    try:
        settings = SecuritySettings(deployment_mode, allowed_hosts)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    return authenticator, settings


def from_environment():
    dsn = os.environ.get("KIBAN_POSTGRES_DSN")
    root = os.environ.get("KIBAN_SNAPSHOT_ROOT")
    report_root = os.environ.get("KIBAN_REPORT_ROOT")
    if not dsn or not root or not report_root:
        raise RuntimeError(
            "KIBAN_POSTGRES_DSN、KIBAN_SNAPSHOT_ROOT、KIBAN_REPORT_ROOTを設定してください"
        )
    authenticator, security_settings = load_api_security(os.environ)
    return create_app(
        PostgresRunStore(dsn),
        PostgresCatalogStore(dsn),
        authenticator,
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
        security_settings=security_settings,
    )
