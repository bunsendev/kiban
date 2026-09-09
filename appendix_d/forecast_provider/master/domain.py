"""名寄せjob・承認・有効期間の業務規則。"""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime

from .contracts import CanonicalProduct, HandlingPeriod, JanMapping, MatchingDecision, MatchingJob


def make_matching_job(definition: dict) -> MatchingJob:
    allowed = {
        "normalization_ids",
        "policy_version",
        "similarity_threshold",
        "handoff_similarity_threshold",
        "max_handoff_gap_days",
    }
    if set(definition) != allowed:
        raise ValueError("名寄せjob定義の項目が契約と一致しません")
    ids = definition["normalization_ids"]
    if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
        raise ValueError("normalization_idsは重複のない非空listです")
    if not all(isinstance(value, str) and value for value in ids):
        raise ValueError("normalization_idは空でない文字列です")
    for name in ("similarity_threshold", "handoff_similarity_threshold"):
        value = definition[name]
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
            raise ValueError(f"{name}は0以上1以下です")
    if definition["handoff_similarity_threshold"] > definition["similarity_threshold"]:
        raise ValueError("handoff用類似度は通常類似度以下です")
    if (
        isinstance(definition["max_handoff_gap_days"], bool)
        or not isinstance(definition["max_handoff_gap_days"], int)
        or not (0 <= definition["max_handoff_gap_days"] <= 366)
    ):
        raise ValueError("max_handoff_gap_daysは0以上366以下です")
    if not isinstance(definition["policy_version"], str) or not definition["policy_version"]:
        raise ValueError("policy_versionは必須です")
    normalized_definition = {**definition, "normalization_ids": sorted(ids)}
    canonical = _canonical(normalized_definition)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    return MatchingJob(f"matching-{fingerprint}", 1, fingerprint, json.loads(canonical), "QUEUED")


def make_product(display_name: str, created_by: str, reason: str) -> CanonicalProduct:
    _required(display_name=display_name, created_by=created_by, reason=reason)
    return CanonicalProduct(
        str(uuid.uuid4()), display_name, created_by, reason, datetime.now(UTC).isoformat()
    )


def make_decision(
    candidate_id: str,
    decision: str,
    left_product_id: str | None,
    right_product_id: str | None,
    mapping_version: str,
    approved_by: str,
    reason: str,
) -> MatchingDecision:
    _required(
        candidate_id=candidate_id,
        decision=decision,
        mapping_version=mapping_version,
        approved_by=approved_by,
        reason=reason,
    )
    if decision == "UNRESOLVED":
        if left_product_id is not None or right_product_id is not None:
            raise ValueError("UNRESOLVEDにはproductを指定しません")
    elif not left_product_id or not right_product_id:
        raise ValueError("確定判断には左右のcanonical productが必要です")
    elif decision == "SAME_PRODUCT" and left_product_id != right_product_id:
        raise ValueError("SAME_PRODUCTは左右が同じcanonical productです")
    elif decision in {"DIFFERENT_PRODUCT", "SUCCESSOR"} and left_product_id == right_product_id:
        raise ValueError(f"{decision}は左右が異なるcanonical productです")
    elif decision not in {"SAME_PRODUCT", "DIFFERENT_PRODUCT", "SUCCESSOR"}:
        raise ValueError("decisionが不正です")
    return MatchingDecision(
        str(uuid.uuid4()),
        candidate_id,
        decision,
        left_product_id,
        right_product_id,
        mapping_version,
        approved_by,
        reason,
        datetime.now(UTC).isoformat(),
    )


def make_jan_mapping(
    jan: str,
    canonical_product_id: str,
    valid_from: str,
    valid_to: str | None,
    mapping_version: str,
    approved_by: str,
    reason: str,
) -> JanMapping:
    _required(
        jan=jan,
        canonical_product_id=canonical_product_id,
        valid_from=valid_from,
        mapping_version=mapping_version,
        approved_by=approved_by,
        reason=reason,
    )
    _period(valid_from, valid_to)
    return JanMapping(
        str(uuid.uuid4()),
        jan,
        canonical_product_id,
        valid_from,
        valid_to,
        mapping_version,
        approved_by,
        reason,
        datetime.now(UTC).isoformat(),
    )


def make_handling_period(
    canonical_product_id: str,
    center_id: str,
    valid_from: str,
    valid_to: str | None,
    status: str,
    period_version: str,
    approved_by: str,
    basis: str,
) -> HandlingPeriod:
    _required(
        canonical_product_id=canonical_product_id,
        center_id=center_id,
        valid_from=valid_from,
        status=status,
        period_version=period_version,
        approved_by=approved_by,
        basis=basis,
    )
    if status not in {"CONFIRMED", "TENTATIVE"}:
        raise ValueError("取扱期間statusが不正です")
    _period(valid_from, valid_to)
    return HandlingPeriod(
        str(uuid.uuid4()),
        canonical_product_id,
        center_id,
        valid_from,
        valid_to,
        status,
        period_version,
        approved_by,
        basis,
        datetime.now(UTC).isoformat(),
    )


def periods_overlap(
    left_from: str, left_to: str | None, right_from: str, right_to: str | None
) -> bool:
    left_start = date.fromisoformat(left_from)
    left_end = date.max if left_to is None else date.fromisoformat(left_to)
    right_start = date.fromisoformat(right_from)
    right_end = date.max if right_to is None else date.fromisoformat(right_to)
    return left_start <= right_end and right_start <= left_end


def _period(valid_from, valid_to):
    start = date.fromisoformat(valid_from)
    if valid_to is not None and date.fromisoformat(valid_to) < start:
        raise ValueError("valid_toはvalid_from以降です")


def _required(**values):
    empty = [name for name, value in values.items() if not isinstance(value, str) or not value]
    if empty:
        raise ValueError(f"必須項目が空です: {', '.join(empty)}")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
