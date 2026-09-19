"""モデル精度変化レビューの追記型永続契約。"""

from dataclasses import dataclass
from typing import Literal, Protocol

ReviewConclusion = Literal[
    "INVESTIGATING",
    "DATA_ISSUE",
    "BUSINESS_EVENT",
    "MODEL_ISSUE",
    "NO_ACTION",
]


@dataclass(frozen=True)
class ModelDriftReview:
    review_id: str
    comparison_profile_id: str
    decision_version: str
    conclusion: ReviewConclusion
    reviewed_by: str
    reason: str
    action: str
    evidence_sha256: str
    evidence: dict
    reviewed_at: str


class ModelReviewStore(Protocol):
    def put(self, value: ModelDriftReview) -> ModelDriftReview: ...

    def get(self, review_id: str) -> ModelDriftReview | None: ...

    def list(
        self, *, comparison_profile_id: str | None = None, limit: int = 200
    ) -> list[ModelDriftReview]: ...
