"""JAN名寄せ候補・承認・商品master。"""

from .candidates import generate_candidates
from .contracts import (
    CanonicalProduct,
    HandlingPeriod,
    JanMapping,
    MatchingCandidate,
    MatchingDecision,
    MatchingJob,
)
from .domain import (
    make_decision,
    make_handling_period,
    make_jan_mapping,
    make_matching_job,
    make_product,
)
from .names import name_similarity, normalize_product_name
from .postgres_store import PostgresMasterStore
from .processor import MatchingProcessor
from .store import SqliteMasterStore

__all__ = [
    "CanonicalProduct",
    "HandlingPeriod",
    "JanMapping",
    "MatchingCandidate",
    "MatchingDecision",
    "MatchingJob",
    "MatchingProcessor",
    "PostgresMasterStore",
    "SqliteMasterStore",
    "generate_candidates",
    "make_decision",
    "make_handling_period",
    "make_jan_mapping",
    "make_matching_job",
    "make_product",
    "name_similarity",
    "normalize_product_name",
]
