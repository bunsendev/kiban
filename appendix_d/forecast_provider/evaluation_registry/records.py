"""評価レジストリのJSON表現とDB行変換。"""

import json

from .contracts import ComparisonRecord, ConformanceCheck, ProviderConformance, RunEvaluation


def encode_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def conformance_from_row(row) -> ProviderConformance:
    return ProviderConformance(
        row["conformance_id"],
        int(row["format_version"]),
        row["condition_fingerprint"],
        row["provider_id"],
        row["provider_version"],
        row["model_id"],
        row["library_name"],
        row["library_version"],
        row["test_suite_version"],
        json.loads(row["adapter_config_json"]),
        json.loads(row["environment_json"]),
        tuple(ConformanceCheck(**item) for item in json.loads(row["checks_json"])),
        row["status"],
        bool(row["fixed_ranking_eligible"]),
        row["executed_by"],
        row["executed_at"],
        row["evidence_uri"],
        row["evidence_sha256"],
    )


def comparison_from_row(row) -> ComparisonRecord:
    return ComparisonRecord(
        row["comparison_id"],
        int(row["format_version"]),
        row["condition_fingerprint"],
        json.loads(row["definition_json"]),
        json.loads(row["result_json"]),
        row["created_at"],
    )


def evaluation_from_row(row) -> RunEvaluation:
    return RunEvaluation(
        row["comparison_id"],
        row["run_id"],
        row["provider_id"],
        row["model_name"],
        row["conformance_id"],
        json.loads(row["score_json"]),
    )
