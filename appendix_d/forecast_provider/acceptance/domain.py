"""受入caseと業務判断の検証・識別。"""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from .contracts import AcceptanceCase, AcceptanceDecision

FORMAT_VERSION = 1


def make_acceptance_case(definition: dict) -> AcceptanceCase:
    required = {
        "acceptance_version",
        "daily_build_id",
        "data_kind",
        "expected_product_ids",
        "required_availability_mode",
        "min_usable_days_per_series",
        "max_missing_rate",
        "max_partial_invalid_rate",
        "requested_by",
        "purpose",
    }
    if set(definition) != required:
        raise ValueError("受入case定義の項目が契約と一致しません")
    _required(
        acceptance_version=definition["acceptance_version"],
        daily_build_id=definition["daily_build_id"],
        requested_by=definition["requested_by"],
        purpose=definition["purpose"],
    )
    if definition["data_kind"] not in {"REAL", "ANONYMIZED"}:
        raise ValueError("data_kindはREALまたはANONYMIZEDです")
    if definition["required_availability_mode"] not in {"ASSUMED", "OBSERVED"}:
        raise ValueError("required_availability_modeが不正です")
    product_ids = definition["expected_product_ids"]
    if (
        not isinstance(product_ids, list)
        or not 3 <= len(product_ids) <= 5
        or len(product_ids) != len(set(product_ids))
        or not all(isinstance(value, str) and value for value in product_ids)
    ):
        raise ValueError("expected_product_idsは重複のない3〜5件です")
    minimum = definition["min_usable_days_per_series"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValueError("min_usable_days_per_seriesは1以上の整数です")
    for name in ("max_missing_rate", "max_partial_invalid_rate"):
        value = definition[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(f"{name}は0以上1以下です")
    normalized = {
        **definition,
        "expected_product_ids": sorted(product_ids),
        "max_missing_rate": float(definition["max_missing_rate"]),
        "max_partial_invalid_rate": float(definition["max_partial_invalid_rate"]),
    }
    fingerprint = _digest(normalized)
    return AcceptanceCase(
        f"acceptance-{fingerprint}", FORMAT_VERSION, fingerprint, normalized, "QUEUED"
    )


def make_acceptance_decision(
    case_id: str,
    decision_version: str,
    decision: str,
    decided_by: str,
    reason: str,
) -> AcceptanceDecision:
    _required(
        case_id=case_id,
        decision_version=decision_version,
        decided_by=decided_by,
        reason=reason,
    )
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("decisionはAPPROVEDまたはREJECTEDです")
    return AcceptanceDecision(
        str(uuid.uuid4()),
        case_id,
        decision_version,
        decision,
        decided_by,
        reason,
        datetime.now(UTC).isoformat(),
    )


def _required(**values) -> None:
    empty = [name for name, value in values.items() if not isinstance(value, str) or not value]
    if empty:
        raise ValueError(f"必須項目が空です: {', '.join(empty)}")


def _digest(value: dict) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
