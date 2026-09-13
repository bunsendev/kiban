"""DiscoveryとJWKSの決定的な互換性判定。"""

from __future__ import annotations

from typing import Any

from .contracts import OidcPreflightSettings, require_https_url


def check(check_id: str, passed: bool, actual: Any, expected: Any) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "PASSED" if passed else "FAILED",
        "actual": actual,
        "expected": expected,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return list(dict.fromkeys(value))


def _secure_endpoint(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        require_https_url(value, "endpoint")
    except ValueError:
        return False
    return True


def validate_discovery(
    settings: OidcPreflightSettings, metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    response_types = _string_list(metadata.get("response_types_supported"))
    grant_types_value = metadata.get("grant_types_supported")
    grant_types = (
        ["authorization_code", "implicit"]
        if grant_types_value is None
        else _string_list(grant_types_value)
    )
    pkce_methods = _string_list(metadata.get("code_challenge_methods_supported"))
    signing_algorithms = _string_list(metadata.get("id_token_signing_alg_values_supported"))
    endpoints = {
        "authorization_endpoint": settings.authorization_url,
        "token_endpoint": settings.token_url,
        "jwks_uri": settings.jwks_url,
    }
    endpoint_values = {name: metadata.get(name) for name in endpoints}
    return [
        check(
            "DISCOVERY_ISSUER",
            metadata.get("issuer") == settings.issuer,
            "MATCH" if metadata.get("issuer") == settings.issuer else "MISMATCH",
            "MATCH",
        ),
        check(
            "DISCOVERY_ENDPOINTS_HTTPS",
            all(_secure_endpoint(value) for value in endpoint_values.values()),
            sum(_secure_endpoint(value) for value in endpoint_values.values()),
            3,
        ),
        check(
            "AUTHORIZATION_ENDPOINT",
            endpoint_values["authorization_endpoint"] == settings.authorization_url,
            "MATCH"
            if endpoint_values["authorization_endpoint"] == settings.authorization_url
            else "MISMATCH",
            "MATCH",
        ),
        check(
            "TOKEN_ENDPOINT",
            endpoint_values["token_endpoint"] == settings.token_url,
            "MATCH" if endpoint_values["token_endpoint"] == settings.token_url else "MISMATCH",
            "MATCH",
        ),
        check(
            "JWKS_URI",
            endpoint_values["jwks_uri"] == settings.jwks_url,
            "MATCH" if endpoint_values["jwks_uri"] == settings.jwks_url else "MISMATCH",
            "MATCH",
        ),
        check("RESPONSE_TYPE_CODE", "code" in response_types, "code" in response_types, True),
        check(
            "AUTHORIZATION_CODE_GRANT",
            "authorization_code" in grant_types,
            "authorization_code" in grant_types,
            True,
        ),
        check("PKCE_S256", "S256" in pkce_methods, "S256" in pkce_methods, True),
        check(
            "SIGNING_ALGORITHM",
            bool(set(settings.algorithms) & set(signing_algorithms)),
            sorted(set(settings.algorithms) & set(signing_algorithms)),
            list(settings.algorithms),
        ),
    ]


def _compatible_key(key: Any, algorithms: tuple[str, ...]) -> bool:
    if not isinstance(key, dict):
        return False
    if key.get("use") not in (None, "sig"):
        return False
    if key.get("key_ops") is not None and "verify" not in _string_list(key["key_ops"]):
        return False
    algorithm = key.get("alg")
    if algorithm is not None and algorithm not in algorithms:
        return False
    key_type = key.get("kty")
    if key_type == "RSA":
        compatible = set(algorithms) & {"RS256", "RS384", "RS512"}
        return bool(compatible) and all(
            isinstance(key.get(name), str) and key[name] for name in ("n", "e")
        )
    if key_type == "EC":
        curve_algorithms = {"P-256": "ES256", "P-384": "ES384", "P-521": "ES512"}
        curve_algorithm = curve_algorithms.get(key.get("crv"))
        return (
            curve_algorithm in algorithms
            and algorithm in (None, curve_algorithm)
            and all(isinstance(key.get(name), str) and key[name] for name in ("x", "y"))
        )
    if key_type == "OKP":
        return (
            "EdDSA" in algorithms
            and key.get("crv") in {"Ed25519", "Ed448"}
            and isinstance(key.get("x"), str)
            and bool(key["x"])
        )
    return False


def validate_jwks(algorithms: tuple[str, ...], jwks: dict[str, Any]) -> list[dict[str, Any]]:
    keys = jwks.get("keys")
    keys = keys if isinstance(keys, list) else []
    compatible = [key for key in keys if _compatible_key(key, algorithms)]
    kids = [key.get("kid") for key in compatible if isinstance(key, dict)]
    valid_kids = [kid for kid in kids if isinstance(kid, str) and 1 <= len(kid) <= 200]
    return [
        check(
            "JWKS_KEY_SET",
            bool(keys) and len(keys) <= 100,
            len(keys),
            {"minimum": 1, "maximum": 100},
        ),
        check("JWKS_COMPATIBLE_SIGNING_KEY", bool(compatible), len(compatible), {"minimum": 1}),
        check(
            "JWKS_UNIQUE_KEY_IDS",
            len(valid_kids) == len(compatible) == len(set(valid_kids)),
            len(set(valid_kids)),
            len(compatible),
        ),
    ]
