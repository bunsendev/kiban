"""レビュー対応から比較キャンペーンを再登録し、結果を履歴へ同期する。"""

import hashlib
from dataclasses import asdict
from types import SimpleNamespace

from .action_service import ReviewActionNotFound
from .actions import ActionConflict
from .retest_comparison import (
    summarize_retest_comparison,
    unavailable_retest_comparison,
)
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
        items = self.retests.list(action_id=action_id, limit=limit)
        drift = None
        if any(item.outcome_status == "SUCCEEDED" for item in items):
            drift = self.campaigns.result_matrix(limit=200)["model_drift"]
        return [self._output(item, drift=drift) for item in items]

    def _output(self, item, *, drift: dict | None = None) -> dict:
        value = asdict(item)
        action = self.actions.get(item.action_id)
        review = None if action is None else self.reviews.get(action.task.review_id)
        if review is not None:
            value["source_review_id"] = review.review_id
            value["review_provider_id"] = review.evidence.get("provider_id")
            value["review_model_id"] = review.evidence.get("model_id")
        if item.outcome_status is not None:
            value["status"] = item.outcome_status
            if item.outcome_status == "SUCCEEDED":
                value["comparison_summary"] = self._comparison_summary(
                    item, review, drift=drift
                )
            return value
        detail = self.campaigns.detail(item.campaign_id)
        finalization = detail.get("finalization") or {}
        value["status"] = (
            "FAILED"
            if detail["status"] == "NEEDS_ATTENTION" or finalization.get("status") == "FAILED"
            else "RUNNING"
        )
        return value

    def _comparison_summary(self, item, review, *, drift: dict | None) -> dict:
        source = self.campaigns.result(item.source_campaign_id)
        retest = self.campaigns.result(item.campaign_id)
        if source is None or retest is None:
            return unavailable_retest_comparison(
                "元結果または追加テスト結果の公式指標を取得できません"
            )
        provider_id = None if review is None else review.evidence.get("provider_id")
        model_id = None if review is None else review.evidence.get("model_id")
        summary = summarize_retest_comparison(
            source,
            retest,
            focus_provider_id=provider_id,
            focus_model_id=model_id,
        )
        summary["review_handoff"] = self._review_handoff(
            item.campaign_id, provider_id, model_id, drift=drift
        )
        return summary

    def _review_handoff(
        self,
        campaign_id: str,
        provider_id: str | None,
        model_id: str | None,
        *,
        drift: dict | None,
    ) -> dict | None:
        if provider_id is None or model_id is None:
            return None
        drift = drift or self.campaigns.result_matrix(limit=200)["model_drift"]
        series = next(
            (
                item
                for item in drift["series"]
                if item["provider_id"] == provider_id
                and item["model_id"] == model_id
                and item["history_count"] >= 2
                and item["latest"]["campaign_id"] == campaign_id
            ),
            None,
        )
        if series is None:
            return None
        return {
            "comparison_profile_id": series["comparison_profile_id"],
            "direction": series["direction"],
        }


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
