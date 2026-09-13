"""外部IdPのDiscoveryとJWKS取得・判定・証跡保存を統合する。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .contracts import FORMAT_VERSION, OidcPreflightSettings
from .fetcher import FetchError, HttpsJsonFetcher, JsonFetcher
from .report import fingerprint, publish_report
from .validation import check, validate_discovery, validate_jwks


def collect_preflight(
    settings: OidcPreflightSettings,
    *,
    fetcher: JsonFetcher | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    client = fetcher or HttpsJsonFetcher(settings.timeout_seconds, settings.max_response_bytes)
    checks: list[dict] = []
    observations: dict = {}
    try:
        discovery = client.fetch(settings.discovery_url)
    except FetchError:
        checks.append(check("DISCOVERY_HTTPS_FETCH", False, False, True))
        discovery = None
    else:
        checks.append(check("DISCOVERY_HTTPS_FETCH", True, True, True))
        observations["discovery"] = {
            "content_type": discovery.content_type,
            "elapsed_ms": discovery.elapsed_ms,
            "size_limited": True,
        }
        checks.extend(validate_discovery(settings, discovery.value))

    try:
        jwks = client.fetch(settings.jwks_url)
    except FetchError:
        checks.append(check("JWKS_HTTPS_FETCH", False, False, True))
    else:
        checks.append(check("JWKS_HTTPS_FETCH", True, True, True))
        observations["jwks"] = {
            "content_type": jwks.content_type,
            "elapsed_ms": jwks.elapsed_ms,
            "size_limited": True,
        }
        checks.extend(validate_jwks(settings.algorithms, jwks.value))

    conditions = settings.public_conditions()
    return {
        "format_version": FORMAT_VERSION,
        "preflight_id": fingerprint(conditions),
        "checked_at": now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "conditions": conditions,
        "outcome": "READY_FOR_IDP_LOGIN"
        if checks and all(item["status"] == "PASSED" for item in checks)
        else "BLOCKED",
        "checks": checks,
        "observations": observations,
        "limitations": [
            "client登録、redirect URI、audience、role claim、管理者同意は検査していない。",
            "実tokenの発行、署名・claim検証、logout・失効連携は検査していない。",
            "READY_FOR_IDP_LOGINは取得時点の公開metadataと鍵の技術互換性だけを示す。",
        ],
    }


def run_preflight(settings: OidcPreflightSettings, output_root: Path) -> dict:
    payload = collect_preflight(settings)
    report_uri, report_sha256 = publish_report(payload, output_root)
    return {
        "preflight_id": payload["preflight_id"],
        "outcome": payload["outcome"],
        "report_uri": report_uri,
        "report_sha256": report_sha256,
    }
