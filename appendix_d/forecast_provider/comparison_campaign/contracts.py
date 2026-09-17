"""複数Provider比較キャンペーンの永続契約。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ComparisonCampaign:
    campaign_id: str
    request_key_hash: str
    snapshot_id: str
    requested_by: str
    purpose: str
    model_keys: str
    created_at: str


@dataclass(frozen=True)
class CampaignEntry:
    campaign_id: str
    provider_id: str
    model_id: str
    experiment_id: str
    conformance_job_id: str
    run_id: str


@dataclass(frozen=True)
class CampaignFinalization:
    campaign_id: str
    mode: str
    horizon: int | None
    policy_version: str
    status: str
    requested_at: str
    started_at: str | None = None
    finished_at: str | None = None
    comparison_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class ComparisonCampaignStore(Protocol):
    def reserve(
        self, request_key_hash: str, snapshot_id: str, requested_by: str, purpose: str,
        model_keys: str, mode: str = "primary", horizon: int | None = None,
        policy_version: str = "evaluation-v2.9",
    ) -> tuple[ComparisonCampaign, bool]: ...

    def put_entry(self, value: CampaignEntry) -> CampaignEntry: ...
    def get(self, campaign_id: str) -> ComparisonCampaign | None: ...
    def get_by_request(
        self, requested_by: str, request_key_hash: str
    ) -> ComparisonCampaign | None: ...
    def list(self, *, limit: int = 100) -> list[ComparisonCampaign]: ...
    def list_entries(self, campaign_id: str) -> list[CampaignEntry]: ...
    def get_finalization(self, campaign_id: str) -> CampaignFinalization | None: ...
    def claim_finalization(self) -> CampaignFinalization | None: ...
    def defer_finalization(self, campaign_id: str) -> None: ...
    def complete_finalization(self, campaign_id: str, comparison_id: str) -> None: ...
    def fail_finalization(
        self, campaign_id: str, error_code: str, error_message: str
    ) -> None: ...
    def retry_finalization(self, campaign_id: str) -> CampaignFinalization: ...
