"""ASGI server用factory。"""

import json
import os
from collections.abc import Mapping
from pathlib import Path

from ..acceptance import PostgresAcceptanceStore
from ..catalog import PostgresCatalogStore
from ..comparison_campaign import PostgresComparisonCampaignStore
from ..daily import PostgresDailyStore
from ..evaluation_registry import PostgresEvaluationRegistryStore
from ..ingestion import PostgresIngestionStore
from ..inventory_normalization import PostgresInventoryNormalizationStore
from ..jobs import PostgresRunStore
from ..lifecycle import PostgresLifecycleStore
from ..mapping_dry_run import PostgresMappingDryRunJobStore
from ..master import PostgresMasterStore
from ..model_review import (
    PostgresModelReviewStore,
    PostgresReviewActionStore,
    PostgresReviewRetestStore,
)
from ..normalization import PostgresNormalizationStore
from ..operation_events import PostgresOperationEventStore
from ..provider_conformance import PostgresConformanceJobStore
from ..reporting import PostgresReportingStore
from ..resource_cost.postgres_store import PostgresResourceCostStore
from ..runtime_config import read_secret_file
from ..selection import PostgresSelectionStore
from ..worker_status import PostgresWorkerStatusStore
from .app import create_app
from .authentication import Authenticator, ReloadingTokenAuthenticator, Role, TokenAuthenticator
from .http_security import SecuritySettings
from .idempotency import PostgresIdempotencyStore
from .oidc_login import OidcLoginSettings


def _postgres_readiness(dsn: str) -> bool:
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
    except Exception:
        return False


def _readable_directory(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.R_OK)


def _writable_directory(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.R_OK | os.W_OK)


def load_secret_setting(
    environment: Mapping[str, str], name: str, *, max_bytes: int = 65_536
) -> str | None:
    value = environment.get(name)
    file_name = environment.get(f"{name}_FILE")
    if value and file_name:
        raise RuntimeError(f"{name}と{name}_FILEは同時に設定できません")
    if file_name:
        path = Path(file_name)
        try:
            return read_secret_file(path, f"{name}_FILE", max_bytes)
        except ValueError as exc:
            raise RuntimeError(f"{name}_FILEを読込めません") from exc
    return value


def _oidc_authenticator(environment: Mapping[str, str]) -> Authenticator:
    try:
        from .oidc import OidcAuthenticator, OidcSettings
    except ImportError as exc:
        raise RuntimeError("OIDC modeにはauth依存が必要です") from exc

    required_names = ("KIBAN_OIDC_ISSUER", "KIBAN_OIDC_AUDIENCE", "KIBAN_OIDC_JWKS_URL")
    values = {name: environment.get(name) for name in required_names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"OIDC設定が不足しています: {', '.join(missing)}")
    try:
        raw_mapping = json.loads(environment.get("KIBAN_OIDC_ROLE_MAPPING", "{}"))
        if not isinstance(raw_mapping, dict) or len(raw_mapping) > 100:
            raise ValueError
        mapping = tuple((str(external), Role(local)) for external, local in raw_mapping.items())
        algorithms = tuple(
            value.strip()
            for value in environment.get("KIBAN_OIDC_ALGORITHMS", "RS256").split(",")
            if value.strip()
        )
        settings = OidcSettings(
            issuer=values["KIBAN_OIDC_ISSUER"] or "",
            audience=values["KIBAN_OIDC_AUDIENCE"] or "",
            jwks_url=values["KIBAN_OIDC_JWKS_URL"] or "",
            role_claim=environment.get("KIBAN_OIDC_ROLE_CLAIM", "roles"),
            role_mapping=mapping,
            algorithms=algorithms,
            leeway_seconds=int(environment.get("KIBAN_OIDC_LEEWAY_SECONDS", "60")),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("OIDC設定が不正です") from exc
    return OidcAuthenticator(settings)


def load_api_security(
    environment: Mapping[str, str],
) -> tuple[Authenticator, SecuritySettings]:
    auth_mode = environment.get("KIBAN_AUTH_MODE", "token")
    token = environment.get("KIBAN_API_TOKEN")
    credentials_json = environment.get("KIBAN_API_CREDENTIALS")
    credentials_file = environment.get("KIBAN_API_CREDENTIALS_FILE")
    deployment_mode = environment.get("KIBAN_DEPLOYMENT_MODE", "development")
    allowed_hosts = tuple(
        dict.fromkeys(
            value.strip()
            for value in environment.get("KIBAN_ALLOWED_HOSTS", "").split(",")
            if value.strip()
        )
    )
    token_settings = [value for value in (token, credentials_json, credentials_file) if value]
    if auth_mode == "oidc":
        if token_settings:
            raise RuntimeError("oidc modeではtoken credentialを同時に設定できません")
        authenticator = _oidc_authenticator(environment)
    elif auth_mode == "token":
        if len(token_settings) > 1:
            raise RuntimeError("token credential設定は1種類だけ指定してください")
        try:
            if credentials_file:
                interval = float(environment.get("KIBAN_CREDENTIAL_REFRESH_SECONDS", "5"))
                authenticator = ReloadingTokenAuthenticator(
                    Path(credentials_file), refresh_interval_seconds=interval
                )
            elif credentials_json:
                authenticator = TokenAuthenticator.from_json(credentials_json)
            elif token:
                if deployment_mode == "production":
                    raise RuntimeError(
                        "productionではKIBAN_API_CREDENTIALSまたは"
                        "KIBAN_API_CREDENTIALS_FILEを使用してください"
                    )
                authenticator = TokenAuthenticator.single(
                    token,
                    environment.get("KIBAN_API_SUBJECT", "local-admin"),
                )
            else:
                raise RuntimeError("token credentialを設定してください")
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
    else:
        raise RuntimeError("KIBAN_AUTH_MODEはtokenまたはoidcです")
    try:
        settings = SecuritySettings(deployment_mode, allowed_hosts)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    return authenticator, settings


def load_oidc_login_settings(environment: Mapping[str, str]) -> OidcLoginSettings | None:
    names = (
        "KIBAN_OIDC_AUTHORIZATION_URL",
        "KIBAN_OIDC_TOKEN_URL",
        "KIBAN_OIDC_CLIENT_ID",
    )
    values = [environment.get(name) for name in names]
    if not any(values):
        return None
    if not all(values):
        missing = [name for name, value in zip(names, values, strict=True) if not value]
        raise RuntimeError(f"OIDC UI login設定が不足しています: {', '.join(missing)}")
    scopes = tuple(
        value for value in environment.get("KIBAN_OIDC_SCOPES", "openid profile").split() if value
    )
    try:
        return OidcLoginSettings(values[0] or "", values[1] or "", values[2] or "", scopes)
    except ValueError as exc:
        raise RuntimeError("OIDC UI login設定が不正です") from exc


def from_environment():
    dsn = load_secret_setting(os.environ, "KIBAN_POSTGRES_DSN", max_bytes=8_192)
    root = os.environ.get("KIBAN_SNAPSHOT_ROOT")
    report_root = os.environ.get("KIBAN_REPORT_ROOT")
    if not dsn or not root or not report_root:
        raise RuntimeError(
            "KIBAN_POSTGRES_DSN、KIBAN_SNAPSHOT_ROOT、KIBAN_REPORT_ROOTを設定してください"
        )
    authenticator, security_settings = load_api_security(os.environ)
    snapshot_root = Path(root)
    reporting_root = Path(report_root)
    mapping_dry_run_value = os.environ.get("KIBAN_MAPPING_DRY_RUN_DIR")
    mapping_dry_run_root = Path(mapping_dry_run_value) if mapping_dry_run_value else None
    import_root_value = os.environ.get("KIBAN_IMPORT_ROOT")
    import_root = Path(import_root_value) if import_root_value else None
    mapping_dry_run_jobs = PostgresMappingDryRunJobStore(dsn)
    readiness_checks = {
        "postgres": lambda: _postgres_readiness(dsn),
        "snapshot_root": lambda: _readable_directory(snapshot_root),
        "report_root": lambda: _writable_directory(reporting_root),
    }
    if mapping_dry_run_root is not None:
        readiness_checks["mapping_dry_run_root"] = lambda: _readable_directory(
            mapping_dry_run_root
        )
    if import_root is not None:
        readiness_checks["import_root"] = lambda: _readable_directory(import_root)
    runs = PostgresRunStore(dsn)
    catalog = PostgresCatalogStore(dsn)
    evaluation_registry = PostgresEvaluationRegistryStore(dsn)
    conformance_jobs = PostgresConformanceJobStore(dsn)
    comparison_campaigns = PostgresComparisonCampaignStore(dsn)
    model_reviews = PostgresModelReviewStore(dsn)
    review_actions = PostgresReviewActionStore(dsn)
    review_retests = PostgresReviewRetestStore(dsn)
    return create_app(
        runs,
        catalog,
        authenticator,
        snapshot_root,
        PostgresIngestionStore(dsn),
        PostgresNormalizationStore(dsn),
        PostgresMasterStore(dsn),
        PostgresDailyStore(dsn),
        PostgresAcceptanceStore(dsn),
        PostgresSelectionStore(dsn),
        evaluation_registry,
        PostgresReportingStore(dsn),
        reporting_root,
        security_settings=security_settings,
        readiness_checks=readiness_checks,
        lifecycle=PostgresLifecycleStore(dsn),
        oidc_login_settings=load_oidc_login_settings(os.environ),
        mapping_dry_run_root=mapping_dry_run_root,
        mapping_dry_run_jobs=mapping_dry_run_jobs,
        mapping_dry_run_input_root=import_root,
        inventory_normalization=PostgresInventoryNormalizationStore(dsn),
        idempotency_store=PostgresIdempotencyStore(dsn),
        resource_cost=PostgresResourceCostStore(dsn),
        worker_status=PostgresWorkerStatusStore(dsn),
        worker_stale_seconds=float(os.environ.get("KIBAN_WORKER_STALE_SECONDS", "45")),
        conformance_jobs=conformance_jobs,
        comparison_campaigns=comparison_campaigns,
        model_reviews=model_reviews,
        review_actions=review_actions,
        review_retests=review_retests,
        operation_events=PostgresOperationEventStore(dsn),
        operation_event_retention_days=int(
            os.environ.get("KIBAN_OPERATION_EVENT_RETENTION_DAYS", "180")
        ),
    )
