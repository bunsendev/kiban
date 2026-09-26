"""商品名を介したJAN候補を、業務承認とは分離して組み立てる。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProductJanCandidateStatus(StrEnum):
    UNIQUE = "UNIQUE"
    AMBIGUOUS = "AMBIGUOUS"
    MISSING = "MISSING"


@dataclass(frozen=True)
class ProductJanCandidate:
    product_code: str
    product_names: tuple[str, ...]
    candidate_jans: tuple[str, ...]
    direct_candidate_jans: tuple[str, ...]

    @property
    def display_name(self) -> str:
        return self.product_names[0] if self.product_names else ""

    @property
    def status(self) -> ProductJanCandidateStatus:
        if len(self.candidate_jans) == 1:
            return ProductJanCandidateStatus.UNIQUE
        if self.candidate_jans:
            return ProductJanCandidateStatus.AMBIGUOUS
        return ProductJanCandidateStatus.MISSING

    @property
    def unique_candidate_is_direct(self) -> bool:
        return (
            self.status is ProductJanCandidateStatus.UNIQUE
            and self.candidate_jans[0] in self.direct_candidate_jans
        )


def build_product_jan_candidates(
    inventory_names_by_code: dict[str, set[str]],
    shipment_jans_by_name: dict[str, set[str]],
    shipment_jans_by_code: dict[str, set[str]] | None = None,
) -> tuple[ProductJanCandidate, ...]:
    """全名称variantの候補をunionし、商品コードごとの曖昧性を失わず返す。"""

    candidates = []
    shipment_jans_by_code = shipment_jans_by_code or {}
    for product_code, names in sorted(inventory_names_by_code.items()):
        normalized_names = tuple(sorted(value.strip() for value in names if value.strip()))
        name_jans = {
            jan
            for name in normalized_names
            for jan in shipment_jans_by_name.get(name, set())
            if jan
        }
        direct_jans = {
            jan for jan in shipment_jans_by_code.get(product_code, set()) if jan
        }
        jans = name_jans | direct_jans
        candidates.append(
            ProductJanCandidate(
                product_code,
                normalized_names,
                tuple(sorted(jans)),
                tuple(sorted(direct_jans)),
            )
        )
    return tuple(candidates)
