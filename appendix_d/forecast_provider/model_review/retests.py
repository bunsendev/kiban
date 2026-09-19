"""レビュー対応タスクから起動した追加テストの不変リンク。"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class ReviewRetest:
    retest_id: str
    action_id: str
    request_key_hash: str
    source_campaign_id: str
    target_snapshot_id: str
    campaign_id: str
    requested_by: str
    requested_at: str
    outcome_status: str | None = None
    comparison_id: str | None = None
    error_message: str | None = None
    finished_at: str | None = None


def make_review_retest(
    action_id: str,
    request_key: str,
    source_campaign_id: str,
    target_snapshot_id: str,
    campaign_id: str,
    requested_by: str,
) -> ReviewRetest:
    values = {
        "action_id": action_id,
        "request_key": request_key,
        "source_campaign_id": source_campaign_id,
        "target_snapshot_id": target_snapshot_id,
        "campaign_id": campaign_id,
        "requested_by": requested_by,
    }
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise ValueError("追加テストの必須項目が空です")
    return ReviewRetest(
        retest_id=str(uuid.uuid4()),
        action_id=action_id,
        request_key_hash=hashlib.sha256(request_key.encode("utf-8")).hexdigest(),
        source_campaign_id=source_campaign_id,
        target_snapshot_id=target_snapshot_id,
        campaign_id=campaign_id,
        requested_by=requested_by,
        requested_at=datetime.now(UTC).isoformat(),
    )
