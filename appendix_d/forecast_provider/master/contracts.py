"""JAN名寄せ・商品masterの永続型。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchingJob:
    matching_job_id: str
    format_version: int
    condition_fingerprint: str
    definition: dict
    status: str
    error: str | None = None


@dataclass(frozen=True)
class MatchingCandidate:
    candidate_id: str
    matching_job_id: str
    left_jan: str
    right_jan: str
    details: dict


@dataclass(frozen=True)
class CanonicalProduct:
    canonical_product_id: str
    display_name: str
    created_by: str
    reason: str
    created_at: str


@dataclass(frozen=True)
class MatchingDecision:
    decision_id: str
    candidate_id: str
    decision: str
    left_product_id: str | None
    right_product_id: str | None
    mapping_version: str
    approved_by: str
    reason: str
    decided_at: str


@dataclass(frozen=True)
class JanMapping:
    jan_mapping_id: str
    jan: str
    canonical_product_id: str
    valid_from: str
    valid_to: str | None
    mapping_version: str
    approved_by: str
    reason: str
    decided_at: str


@dataclass(frozen=True)
class HandlingPeriod:
    handling_period_id: str
    canonical_product_id: str
    center_id: str
    valid_from: str
    valid_to: str | None
    status: str
    period_version: str
    approved_by: str
    basis: str
    decided_at: str
