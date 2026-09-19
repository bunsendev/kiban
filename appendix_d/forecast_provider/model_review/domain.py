"""モデル精度変化レビューの不変レコード生成。"""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from .contracts import ModelDriftReview

CONCLUSIONS = {
    "INVESTIGATING",
    "DATA_ISSUE",
    "BUSINESS_EVENT",
    "MODEL_ISSUE",
    "NO_ACTION",
}


def make_model_drift_review(
    comparison_profile_id: str,
    decision_version: str,
    conclusion: str,
    reviewed_by: str,
    reason: str,
    action: str,
    evidence: dict,
) -> ModelDriftReview:
    """表示時の指標を証跡として凍結し、レビューを生成する。"""
    _required(
        comparison_profile_id=comparison_profile_id,
        decision_version=decision_version,
        reviewed_by=reviewed_by,
        reason=reason,
        action=action,
    )
    if len(comparison_profile_id) != 64 or any(
        value not in "0123456789abcdef" for value in comparison_profile_id
    ):
        raise ValueError("comparison_profile_idが不正です")
    if conclusion not in CONCLUSIONS:
        raise ValueError("conclusionが不正です")
    encoded = _canonical(evidence)
    frozen_evidence = json.loads(encoded)
    if frozen_evidence.get("comparison_profile_id") != comparison_profile_id:
        raise ValueError("比較プロフィールと証跡が一致しません")
    return ModelDriftReview(
        review_id=str(uuid.uuid4()),
        comparison_profile_id=comparison_profile_id,
        decision_version=decision_version,
        conclusion=conclusion,
        reviewed_by=reviewed_by,
        reason=reason,
        action=action,
        evidence_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
        evidence=frozen_evidence,
        reviewed_at=datetime.now(UTC).isoformat(),
    )


def _required(**values) -> None:
    empty = [name for name, value in values.items() if not isinstance(value, str) or not value]
    if empty:
        raise ValueError(f"必須項目が空です: {', '.join(empty)}")


def _canonical(value: dict) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
