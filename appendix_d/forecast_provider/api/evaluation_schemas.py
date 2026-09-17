"""Provider適合記録とrun比較のHTTP入力。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CheckCode = Literal[
    "TRAIN_BOUNDARY",
    "PARAMETER_IMMUTABILITY",
    "CONTEXT_REFRESH",
    "FUTURE_NON_REFERENCE",
    "OUTPUT_COMPLETENESS",
    "REPRODUCIBILITY",
    "FAILURE_NOTIFICATION",
]


class ConformanceCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: CheckCode
    status: Literal["PASSED", "FAILED", "NOT_APPLICABLE"]
    evidence: str = Field(min_length=1)


class ConformanceEnvironmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    python_version: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    dependencies: dict[str, str] = Field(min_length=1)
    container_digest: str | None = None


class ConformanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    library_name: str = Field(min_length=1)
    library_version: str = Field(min_length=1)
    test_suite_version: str = Field(min_length=1)
    adapter_config: dict
    environment: ConformanceEnvironmentInput
    checks: list[ConformanceCheckInput] = Field(min_length=7, max_length=7)
    executed_by: str | None = Field(default=None, min_length=1)
    executed_at: datetime
    evidence_uri: str | None = None
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_evidence(self):
        if self.executed_at.tzinfo is None or self.executed_at.utcoffset() is None:
            raise ValueError("executed_atはtimezone付きです")
        if (self.evidence_uri is None) != (self.evidence_sha256 is None):
            raise ValueError("証跡URIとSHA-256は同時に指定します")
        return self


class ConformanceJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: str = Field(min_length=1)


class ComparisonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_ids: list[str] = Field(min_length=1)
    conformance_ids: dict[str, str] = Field(min_length=1)
    truth_snapshot_id: str = Field(min_length=1)
    mode: Literal["horizon", "primary"] = "horizon"
    horizon: int | None = Field(default=None, ge=1, le=400)
    policy_version: str = Field(default="evaluation-v2.9", min_length=1)
    requested_by: str | None = Field(default=None, min_length=1)
    purpose: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_runs(self):
        if len(self.run_ids) != len(set(self.run_ids)):
            raise ValueError("run_idsは重複できません")
        if set(self.conformance_ids) != set(self.run_ids):
            raise ValueError("各runに1件のconformance_idが必要です")
        if any(not key or not value for key, value in self.conformance_ids.items()):
            raise ValueError("run_idとconformance_idは空にできません")
        return self
