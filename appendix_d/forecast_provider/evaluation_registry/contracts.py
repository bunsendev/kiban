"""Provider適合記録と比較結果の永続契約。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ConformanceCheck:
    code: str
    status: str
    evidence: str


@dataclass(frozen=True)
class ProviderConformance:
    conformance_id: str
    format_version: int
    condition_fingerprint: str
    provider_id: str
    provider_version: str
    model_id: str
    library_name: str
    library_version: str
    test_suite_version: str
    adapter_config: dict
    environment: dict
    checks: tuple[ConformanceCheck, ...]
    status: str
    fixed_ranking_eligible: bool
    executed_by: str
    executed_at: str
    evidence_uri: str | None
    evidence_sha256: str | None


@dataclass(frozen=True)
class ComparisonRecord:
    comparison_id: str
    format_version: int
    condition_fingerprint: str
    definition: dict
    result: dict
    created_at: str


@dataclass(frozen=True)
class RunEvaluation:
    comparison_id: str
    run_id: str
    provider_id: str
    model_name: str
    conformance_id: str
    score: dict


class EvaluationRegistryStore(Protocol):
    def put_conformance(self, value: ProviderConformance) -> ProviderConformance: ...
    def get_conformance(self, conformance_id: str) -> ProviderConformance | None: ...
    def list_conformance(
        self, provider_id: str | None = None, model_id: str | None = None
    ) -> list[ProviderConformance]: ...
    def put_comparison(
        self, value: ComparisonRecord, scores: list[RunEvaluation]
    ) -> ComparisonRecord: ...
    def get_comparison(self, comparison_id: str) -> ComparisonRecord | None: ...
    def list_comparisons(self, run_id: str | None = None) -> list[ComparisonRecord]: ...
    def list_run_evaluations(self, comparison_id: str) -> list[RunEvaluation]: ...
