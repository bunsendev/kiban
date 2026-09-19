"""レビュー対応から比較キャンペーンを再登録し、結果を履歴へ同期する。"""

import hashlib
from dataclasses import asdict
from types import SimpleNamespace

from .action_service import ReviewActionNotFound
from .actions import ActionConflict
from .retests import make_review_retest


class ReviewRetestService:
    def __init__(self, reviews, actions, retests, campaigns) -> None:
        self.reviews = reviews
        self.actions = actions
        self.retests = retests
        self.campaigns = campaigns

    def start(self, action_id: str, request, actor: str) -> dict:
        request_hash = hashlib.sha256(request.request_key.encode("utf-8")).hexdigest()
        existing = self.retests.get_by_request(action_id, request_hash)
        if existing is not None:
            if (
                existing.target_snapshot_id != request.target_snapshot_id
                or existing.requested_by != actor
            ):
                raise ValueError("同じrequest keyを異なる追加テストには使えません")
            return self._output(existing)
        current = self.actions.get(action_id)
        if current is None:
            raise ReviewActionNotFound(action_id)
        if current.task.action_type != "RETEST":
            raise ActionConflict("追加テスト種別の対応タスクだけを実行できます")
        if current.latest.revision != request.expected_revision:
            raise ActionConflict("ほかの利用者が先に更新しました。再読み込みしてください")
        if current.latest.status not in {"OPEN", "BLOCKED"}:
            raise ActionConflict("未着手または保留の追加テストだけを開始できます")
        review = self.reviews.get(current.task.review_id)
        if review is None:
            raise ReviewActionNotFound(action_id)
        source_campaign_id = review.evidence.get("latest", {}).get("campaign_id")
        if not source_campaign_id:
            raise ValueError("レビュー証跡に元の比較キャンペーンがありません")
        source = self.campaigns.detail(source_campaign_id)
        finalization = source.get("finalization")
        if finalization is None:
            raise ValueError("元の比較キャンペーンに評価条件がありません")
        if finalization["status"] != "SUCCEEDED":
            raise ValueError("完了済みの公式比較だけを追加テストの元にできます")
        expected_comparison_id = review.evidence.get("latest", {}).get("comparison_id")
        if (
            expected_comparison_id is not None
            and finalization["comparison_id"] != expected_comparison_id
        ):
            raise ValueError("レビュー証跡と元の比較結果が一致しません")
        campaign = self.campaigns.create(
            SimpleNamespace(
                request_key=request.request_key,
                snapshot_id=request.target_snapshot_id,
                models=[
                    SimpleNamespace(
                        provider_id=item["provider_id"], model_id=item["model_id"]
                    )
                    for item in source["entries"]
                ],
                purpose=f"レビュー対応再テスト: {current.task.title}"[:500],
                mode=finalization["mode"],
                horizon=finalization["horizon"],
                policy_version=finalization["policy_version"],
            ),
            actor,
        )
        value = make_review_retest(
            action_id,
            request.request_key,
            source_campaign_id,
            request.target_snapshot_id,
            campaign["campaign_id"],
            actor,
        )
        saved = self.retests.reserve_and_start(value, request.expected_revision)
        return self._output(saved)

    def list(self, *, action_id: str | None = None, limit: int = 200) -> list[dict]:
        return [self._output(item) for item in self.retests.list(action_id=action_id, limit=limit)]

    def _output(self, item) -> dict:
        value = asdict(item)
        if item.outcome_status is not None:
            value["status"] = item.outcome_status
            return value
        detail = self.campaigns.detail(item.campaign_id)
        finalization = detail.get("finalization") or {}
        value["status"] = (
            "FAILED"
            if detail["status"] == "NEEDS_ATTENTION" or finalization.get("status") == "FAILED"
            else "RUNNING"
        )
        return value


class ReviewRetestSynchronizer:
    def __init__(self, retests, campaigns) -> None:
        self.retests = retests
        self.campaigns = campaigns

    def sync_pending(self, *, limit: int = 200) -> int:
        synchronized = 0
        for item in self.retests.list_pending(limit=limit):
            finalization = self.campaigns.get_finalization(item.campaign_id)
            if finalization is None:
                continue
            if finalization.status == "SUCCEEDED":
                synchronized += self.retests.finalize(
                    item.campaign_id,
                    "SUCCEEDED",
                    comparison_id=finalization.comparison_id,
                )
            elif finalization.status == "FAILED":
                synchronized += self.retests.finalize(
                    item.campaign_id,
                    "FAILED",
                    error_message=finalization.error_message or "追加テストに失敗しました",
                )
        return synchronized
