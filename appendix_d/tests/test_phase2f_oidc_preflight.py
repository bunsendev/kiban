"""Phase 2F 外部OIDC IdP接続プリフライト。"""

from datetime import UTC, datetime

import pytest

from forecast_provider.oidc_preflight import OidcPreflightSettings, cli
from forecast_provider.oidc_preflight.fetcher import FetchError, HttpsJsonFetcher, JsonDocument
from forecast_provider.oidc_preflight.report import publish_report
from forecast_provider.oidc_preflight.runner import collect_preflight


def _settings(**changes) -> OidcPreflightSettings:
    values = {
        "issuer": "https://id.example.test/tenant",
        "authorization_url": "https://id.example.test/tenant/authorize",
        "token_url": "https://id.example.test/tenant/token",
        "jwks_url": "https://id.example.test/tenant/jwks",
        "algorithms": ("RS256",),
    }
    values.update(changes)
    return OidcPreflightSettings(**values)


def _discovery() -> dict:
    return {
        "issuer": "https://id.example.test/tenant",
        "authorization_endpoint": "https://id.example.test/tenant/authorize",
        "token_endpoint": "https://id.example.test/tenant/token",
        "jwks_uri": "https://id.example.test/tenant/jwks",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


class FakeFetcher:
    def __init__(self, documents: dict[str, dict], failures: set[str] = frozenset()) -> None:
        self.documents = documents
        self.failures = failures

    def fetch(self, url: str) -> JsonDocument:
        if url in self.failures:
            raise FetchError("sanitized")
        return JsonDocument(self.documents[url], "application/json", 12)


def _collect(settings: OidcPreflightSettings, discovery=None, jwks=None) -> dict:
    documents = {
        settings.discovery_url: discovery or _discovery(),
        settings.jwks_url: jwks
        or {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": "active",
                    "alg": "RS256",
                    "use": "sig",
                    "n": "public-modulus",
                    "e": "AQAB",
                }
            ]
        },
    }
    return collect_preflight(
        settings,
        fetcher=FakeFetcher(documents),
        now=lambda: datetime(2026, 9, 13, tzinfo=UTC),
    )


def test_compatible_discovery_and_jwks_are_ready_without_raw_urls():
    report = _collect(_settings())
    assert report["outcome"] == "READY_FOR_IDP_LOGIN"
    assert len(report["checks"]) == 14
    assert all(item["status"] == "PASSED" for item in report["checks"])
    assert (
        report["preflight_id"] == "a35f8cbb98d74db7e58580adb355888528c0a7100cc5cf34a9cb595be6502603"
    )
    assert "id.example.test" not in str(report)
    assert report["limitations"]


@pytest.mark.parametrize(
    ("field", "value", "check_id"),
    [
        ("issuer", "https://other.example.test", "DISCOVERY_ISSUER"),
        ("authorization_endpoint", "http://id.example.test/authorize", "DISCOVERY_ENDPOINTS_HTTPS"),
        ("token_endpoint", "https://id.example.test/wrong", "TOKEN_ENDPOINT"),
        ("jwks_uri", "https://id.example.test/wrong", "JWKS_URI"),
        ("response_types_supported", ["id_token"], "RESPONSE_TYPE_CODE"),
        ("grant_types_supported", ["client_credentials"], "AUTHORIZATION_CODE_GRANT"),
        ("code_challenge_methods_supported", ["plain"], "PKCE_S256"),
        ("id_token_signing_alg_values_supported", ["ES256"], "SIGNING_ALGORITHM"),
    ],
)
def test_discovery_mismatch_blocks(field, value, check_id):
    discovery = _discovery()
    discovery[field] = value
    report = _collect(_settings(), discovery=discovery)
    assert report["outcome"] == "BLOCKED"
    assert (
        next(item for item in report["checks"] if item["check_id"] == check_id)["status"]
        == "FAILED"
    )


@pytest.mark.parametrize(
    "key",
    [
        {"kty": "oct", "kid": "symmetric", "alg": "HS256"},
        {
            "kty": "RSA",
            "kid": "encrypt",
            "alg": "RS256",
            "use": "enc",
            "n": "modulus",
            "e": "AQAB",
        },
        {
            "kty": "RSA",
            "kid": "wrong-op",
            "alg": "RS256",
            "key_ops": ["encrypt"],
            "n": "modulus",
            "e": "AQAB",
        },
        {"kty": "RSA", "kid": "missing-public-components", "alg": "RS256"},
    ],
)
def test_incompatible_jwks_keys_block(key):
    report = _collect(_settings(), jwks={"keys": [key]})
    assert report["outcome"] == "BLOCKED"
    assert (
        next(
            item for item in report["checks"] if item["check_id"] == "JWKS_COMPATIBLE_SIGNING_KEY"
        )["status"]
        == "FAILED"
    )


def test_missing_or_duplicate_kid_blocks_rotation_safety():
    keys = [
        {"kty": "RSA", "kid": "duplicate", "alg": "RS256", "n": "one", "e": "AQAB"},
        {"kty": "RSA", "kid": "duplicate", "alg": "RS256", "n": "two", "e": "AQAB"},
    ]
    report = _collect(_settings(), jwks={"keys": keys})
    assert report["outcome"] == "BLOCKED"
    assert (
        next(item for item in report["checks"] if item["check_id"] == "JWKS_UNIQUE_KEY_IDS")[
            "status"
        ]
        == "FAILED"
    )


def test_network_failure_is_sanitized_and_still_publishes_blocked_report(tmp_path):
    settings = _settings()
    report = collect_preflight(
        settings,
        fetcher=FakeFetcher({}, {settings.discovery_url, settings.jwks_url}),
        now=lambda: datetime(2026, 9, 13, tzinfo=UTC),
    )
    assert report["outcome"] == "BLOCKED"
    assert [item["check_id"] for item in report["checks"]] == [
        "DISCOVERY_HTTPS_FETCH",
        "JWKS_HTTPS_FETCH",
    ]
    uri, checksum = publish_report(report, tmp_path)
    target = next((tmp_path / "oidc-preflight").iterdir())
    assert uri == target.as_uri()
    assert target.name == f"{checksum}.json"
    saved = target.read_text(encoding="utf-8")
    assert "id.example.test" not in saved
    assert "sanitized" not in saved


class _Headers:
    @staticmethod
    def get_content_type():
        return "application/json"


class _Response:
    status = 200
    headers = _Headers()

    def __init__(self, url: str, raw: bytes) -> None:
        self.url = url
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def geturl(self):
        return self.url

    def read(self, maximum):
        return self.raw[:maximum]


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response

    def open(self, request, timeout):
        return self.response


def test_https_fetcher_rejects_redirected_and_oversized_responses():
    url = "https://id.example.test/.well-known/openid-configuration"
    fetcher = HttpsJsonFetcher(1, 1_024)
    fetcher._opener = _Opener(_Response("https://other.example.test/metadata", b"{}"))
    with pytest.raises(FetchError, match="取得に失敗"):
        fetcher.fetch(url)
    fetcher._opener = _Opener(_Response(url, b"{" + b" " * 1_024 + b"}"))
    with pytest.raises(FetchError, match="大きすぎ"):
        fetcher.fetch(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://id.example.test",
        "https://user@id.example.test",
        "https://id.example.test/#fragment",
    ],
)
def test_settings_reject_unsafe_urls(url):
    with pytest.raises(ValueError, match="HTTPS URL"):
        _settings(issuer=url)


def test_settings_reject_issuer_query():
    with pytest.raises(ValueError, match="query"):
        _settings(issuer="https://id.example.test/tenant?configuration=other")


def test_cli_exit_codes_are_machine_readable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "run_preflight",
        lambda settings, output_root: {
            "preflight_id": "a" * 64,
            "outcome": "BLOCKED",
            "report_uri": "file:///report.json",
            "report_sha256": "b" * 64,
        },
    )
    result = cli.main(
        [
            "--issuer",
            "https://id.example.test/tenant",
            "--authorization-url",
            "https://id.example.test/tenant/authorize",
            "--token-url",
            "https://id.example.test/tenant/token",
            "--jwks-url",
            "https://id.example.test/tenant/jwks",
            "--output-root",
            str(tmp_path),
        ]
    )
    assert result == 2
    assert '"outcome": "BLOCKED"' in capsys.readouterr().out
