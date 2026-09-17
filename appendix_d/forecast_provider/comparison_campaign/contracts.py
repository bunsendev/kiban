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


class ComparisonCampaignStore(Protocol):
    def reserve(
        self, request_key_hash: str, snapshot_id: str, requested_by: str, purpose: str,
        model_keys: str,
    ) -> tuple[ComparisonCampaign, bool]: ...

    def put_entry(self, value: CampaignEntry) -> CampaignEntry: ...
    def get(self, campaign_id: str) -> ComparisonCampaign | None: ...
    def get_by_request(
        self, requested_by: str, request_key_hash: str
    ) -> ComparisonCampaign | None: ...
    def list(self, *, limit: int = 100) -> list[ComparisonCampaign]: ...
    def list_entries(self, campaign_id: str) -> list[CampaignEntry]: ...
