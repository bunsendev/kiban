"""適合試験の検証・内容アドレス化と比較条件の固定。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from ..contracts import ProviderMetadata
from .contracts import ComparisonRecord, ConformanceCheck, ProviderConformance

FORMAT_VERSION = 1
REQUIRED_CHECKS = frozenset(
    {
        "TRAIN_BOUNDARY",
        "PARAMETER_IMMUTABILITY",
        "CONTEXT_REFRESH",
        "FUTURE_NON_REFERENCE",
        "OUTPUT_COMPLETENESS",
        "REPRODUCIBILITY",
        "FAILURE_NOTIFICATION",
    }
)
CHECK_STATUSES = frozenset({"PASSED", "FAILED", "NOT_APPLICABLE"})


def make_conformance(definition: dict, metadata: ProviderMetadata) -> ProviderConformance:
    required = {
        "provider_id",
        "provider_version",
        "model_id",
        "library_name",
        "library_version",
        "test_suite_version",
        "adapter_config",
        "environment",
        "checks",
        "executed_by",
        "executed_at",
        "evidence_uri",
        "evidence_sha256",
    }
    if set(definition) != required:
        raise ValueError("Provider適合記録の項目が契約と一致しません")
    model = metadata.get_model(definition["model_id"])
    expected = (
        metadata.provider_id,
        metadata.provider_version,
        metadata.library_name,
        metadata.library_version,
    )
    actual = tuple(
        definition[name]
        for name in ("provider_id", "provider_version", "library_name", "library_version")
    )
    if actual != expected or model is None:
        raise ValueError("登録中Providerのmodel/library識別と一致しません")
    _required(
        test_suite_version=definition["test_suite_version"],
        executed_by=definition["executed_by"],
        executed_at=definition["executed_at"],
    )
    executed_at = _timestamp(definition["executed_at"])
    if not isinstance(definition["adapter_config"], dict):
        raise ValueError("adapter_configはobjectです")
    environment = _environment(definition["environment"])
    checks = _checks(definition["checks"])
    uri, checksum = definition["evidence_uri"], definition["evidence_sha256"]
    if (uri is None) != (checksum is None):
        raise ValueError("証跡URIとSHA-256は同時に指定します")
    if uri is not None:
        _required(evidence_uri=uri)
        if not _sha256(checksum):
            raise ValueError("証跡SHA-256が不正です")

    passed = all(item.status == "PASSED" for item in checks)
    eligible = bool(
        passed
        and metadata.capabilities.eligible_for_primary_ranking
        and model.primary
    )
    normalized = {
        **definition,
        "executed_at": executed_at,
        "adapter_config": _json_value(definition["adapter_config"], "adapter_config"),
        "environment": environment,
        "checks": [item.__dict__ for item in checks],
    }
    fingerprint = digest(normalized)
    return ProviderConformance(
        f"conformance-{fingerprint}",
        FORMAT_VERSION,
        fingerprint,
        metadata.provider_id,
        metadata.provider_version,
        model.model_id,
        metadata.library_name,
        metadata.library_version,
        normalized["test_suite_version"],
        normalized["adapter_config"],
        environment,
        checks,
        "PASSED" if passed else "FAILED",
        eligible,
        normalized["executed_by"],
        normalized["executed_at"],
        uri,
        checksum,
    )


def make_comparison_record(definition: dict, result: dict) -> ComparisonRecord:
    normalized_definition = _json_value(definition, "comparison definition")
    normalized_result = _json_value(result, "comparison result")
    fingerprint = digest(normalized_definition)
    return ComparisonRecord(
        f"comparison-{fingerprint}",
        FORMAT_VERSION,
        fingerprint,
        normalized_definition,
        normalized_result,
        datetime.now(UTC).isoformat(),
    )


def digest(value) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _checks(value) -> tuple[ConformanceCheck, ...]:
    if not isinstance(value, list):
        raise ValueError("checksは配列です")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"code", "status", "evidence"}:
            raise ValueError("適合項目のフィールドが不正です")
        _required(code=item["code"], evidence=item["evidence"])
        if item["status"] not in CHECK_STATUSES:
            raise ValueError("適合項目statusが不正です")
        result.append(ConformanceCheck(item["code"], item["status"], item["evidence"]))
    codes = [item.code for item in result]
    if set(codes) != REQUIRED_CHECKS or len(codes) != len(set(codes)):
        raise ValueError("固定条件の適合試験7項目を重複なく指定します")
    return tuple(sorted(result, key=lambda item: item.code))


def _environment(value) -> dict:
    required = {"python_version", "platform", "dependencies", "container_digest"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("environmentの項目が契約と一致しません")
    _required(python_version=value["python_version"], platform=value["platform"])
    dependencies = value["dependencies"]
    if (
        not isinstance(dependencies, dict)
        or not dependencies
        or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not v
            for k, v in dependencies.items()
        )
    ):
        raise ValueError("environment.dependenciesは空でない版mappingです")
    digest_value = value["container_digest"]
    if digest_value is not None and not _sha256(digest_value.removeprefix("sha256:")):
        raise ValueError("container_digestはSHA-256です")
    return {
        "python_version": value["python_version"],
        "platform": value["platform"],
        "dependencies": dict(sorted(dependencies.items())),
        "container_digest": digest_value,
    }


def _json_value(value, name: str):
    try:
        return json.loads(_json(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}を有限値のJSONへ変換できません") from exc


def _json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _required(**values) -> None:
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError(f"必須文字列が空です: {sorted(values)}")


def _sha256(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("executed_atはISO 8601日時です") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("executed_atはtimezone付きです")
    return parsed.astimezone(UTC).isoformat()
