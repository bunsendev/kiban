"""比較CSV条件と採用判断の検証・内容アドレス化。"""

import hashlib
import json
from datetime import UTC, datetime

from .contracts import AdoptionRecord, ExportRecord

FORMAT_VERSION = 1


def export_identity(definition: dict) -> tuple[str, str, dict]:
    required = {"comparison_id", "export_version", "baseline_run_id", "requested_by"}
    if set(definition) != required:
        raise ValueError("export定義の項目が契約と一致しません")
    _required(**definition)
    normalized = _json_value(definition)
    fingerprint = _digest(normalized)
    return f"export-{fingerprint}", fingerprint, normalized


def make_export_record(
    definition: dict, output_uri: str, output_sha256: str, row_count: int
) -> ExportRecord:
    export_id, fingerprint, normalized = export_identity(definition)
    _required(output_uri=output_uri)
    if not _sha256(output_sha256):
        raise ValueError("export SHA-256が不正です")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 1:
        raise ValueError("export row_countは1以上の整数です")
    return ExportRecord(
        export_id,
        FORMAT_VERSION,
        fingerprint,
        normalized["comparison_id"],
        normalized["export_version"],
        normalized["baseline_run_id"],
        normalized["requested_by"],
        output_uri,
        output_sha256,
        row_count,
        datetime.now(UTC).isoformat(),
    )


def make_adoption(definition: dict) -> AdoptionRecord:
    required = {
        "adoption_version",
        "comparison_id",
        "acceptance_case_id",
        "decision",
        "selected_run_id",
        "fallback_run_id",
        "target",
        "decided_by",
        "reason",
    }
    if set(definition) != required:
        raise ValueError("採用判断の項目が契約と一致しません")
    _required(
        adoption_version=definition["adoption_version"],
        comparison_id=definition["comparison_id"],
        decided_by=definition["decided_by"],
        reason=definition["reason"],
    )
    decision = definition["decision"]
    if decision not in {"ADOPTED", "REJECTED"}:
        raise ValueError("decisionはADOPTEDまたはREJECTEDです")
    references = (
        definition["acceptance_case_id"],
        definition["selected_run_id"],
        definition["fallback_run_id"],
    )
    missing_reference = any(
        not isinstance(value, str) or not value for value in references
    )
    if decision == "ADOPTED" and missing_reference:
        raise ValueError("ADOPTEDには受入case、採用run、fallback runが必要です")
    if decision == "REJECTED" and any(value is not None for value in references):
        raise ValueError("REJECTEDでは受入case・runを指定しません")
    target = _target(definition["target"])
    if definition["selected_run_id"] == definition["fallback_run_id"] is not None:
        raise ValueError("採用runとfallback runは分けます")
    normalized = _json_value({**definition, "target": target})
    fingerprint = _digest(normalized)
    return AdoptionRecord(
        f"adoption-{fingerprint}",
        FORMAT_VERSION,
        fingerprint,
        normalized["adoption_version"],
        normalized["comparison_id"],
        normalized["acceptance_case_id"],
        normalized["decision"],
        normalized["selected_run_id"],
        normalized["fallback_run_id"],
        normalized["target"],
        normalized["decided_by"],
        normalized["reason"],
        datetime.now(UTC).isoformat(),
    )


def _target(value) -> dict:
    required = {
        "selection_version",
        "canonical_product_ids",
        "center_ids",
        "trial_period_days",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("採用対象の項目が契約と一致しません")
    _required(selection_version=value["selection_version"])
    products = _unique_strings(value["canonical_product_ids"], "canonical_product_ids")
    centers = _unique_strings(value["center_ids"], "center_ids")
    days = value["trial_period_days"]
    if isinstance(days, bool) or not isinstance(days, int) or not 30 <= days <= 366:
        raise ValueError("trial_period_daysは30から366です")
    return {
        "selection_version": value["selection_version"],
        "canonical_product_ids": sorted(products),
        "center_ids": sorted(centers),
        "trial_period_days": days,
    }


def _unique_strings(value, name: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) != len(set(value))
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ValueError(f"{name}は重複のない空でない文字列配列です")
    return value


def _required(**values) -> None:
    invalid = [name for name, value in values.items() if not isinstance(value, str) or not value]
    if invalid:
        raise ValueError(f"必須文字列が空です: {sorted(invalid)}")


def _json_value(value):
    try:
        return json.loads(_json(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("有限値のJSONへ変換できません") from exc


def _digest(value) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _sha256(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
