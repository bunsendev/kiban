"""HTTP入出力schema。DB型やrouteから分離する。"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SnapshotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_uri: str = Field(min_length=1)
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_versions_uri: str | None = None
    feature_versions_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    selection_version: str = Field(min_length=1)
    unique_ids: tuple[str, ...] = Field(min_length=1)
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    origin_interval_days: int = Field(ge=1)
    max_horizon: int = Field(ge=1, le=400)
    primary_horizon_max: int = Field(ge=1, le=400)
    report_horizons: tuple[int, ...] = (7, 10, 15)
    known_future_columns: tuple[str, ...] = ()
    availability_mode: Literal["ASSUMED", "OBSERVED"] = "ASSUMED"

    @model_validator(mode="after")
    def validate_feature_source(self):
        if (self.feature_versions_uri is None) != (self.feature_versions_sha256 is None):
            raise ValueError("feature versionsのURIとchecksumは同時に指定します")
        dynamic = [name for name in self.known_future_columns if not name.startswith("calendar_")]
        if dynamic and self.feature_versions_uri is None:
            raise ValueError("変更される将来変数には版テーブルが必要です")
        return self


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    params: dict = Field(default_factory=dict)
    interval_levels: tuple[float, ...] = ()
    preprocessing_version: str = Field(min_length=1)
    seed: int
    resource_profile: str = Field(min_length=1)
    training_policy: Literal["FIXED", "MONTHLY_EXPANDING"] = "FIXED"


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: str = Field(min_length=1)


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition_fingerprint: str = Field(min_length=1)


class Created(BaseModel):
    id: str


class ImportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(min_length=1)


class MappingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_column: str = Field(min_length=1)
    jan_column: str = Field(min_length=1)
    product_name_column: str = Field(min_length=1)
    quantity_column: str = Field(min_length=1)
    unit_column: str | None = None
    unit_value: str | None = None
    center_column: str | None = None
    center_value: str | None = None
    row_type_column: str | None = None
    available_at_column: str | None = None
    date_formats: list[str] = Field(min_length=1)
    allowed_units: list[str] = Field(min_length=1)
    availability_mode: Literal["ASSUMED", "OBSERVED"]
    file_mode: Literal["FULL", "DELTA"]


class MappingDryRunJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(min_length=1, max_length=1_024)
    mapping_id: str = Field(pattern=r"^map-[0-9a-f]{64}$")
    sample_rows: int = Field(default=1_000, ge=1, le=10_000)


class MappingDryRunBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_prefix: str = Field(min_length=1, max_length=1_024)
    mapping_id: str = Field(pattern=r"^map-[0-9a-f]{64}$")
    sample_rows: int = Field(default=1_000, ge=1, le=10_000)


class InventoryProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_prefix: str = Field(min_length=1, max_length=1_024)


class InventoryNormalizationPreviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_prefix: str = Field(min_length=1, max_length=1_024)
    product_mapping_id: str = Field(pattern=r"^product-jan-[0-9a-f]{64}$")
    unit_value: str = Field(min_length=1, max_length=20)
    sample_rows: int = Field(default=100, ge=1, le=1_000)


class InventoryNormalizationJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_prefix: str = Field(min_length=1, max_length=1_024)
    product_mapping_id: str = Field(pattern=r"^product-jan-[0-9a-f]{64}$")
    unit_value: str = Field(min_length=1, max_length=20)


class InventoryNormalizationDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_version: str = Field(min_length=1, max_length=100)
    decision: Literal["APPROVED", "REJECTED"]
    decided_by: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1, max_length=1_000)


class InventoryFeatureViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping_version: str = Field(min_length=1, max_length=100)
    as_of: datetime


class SourceSelectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logical_path: str = Field(min_length=1)
    source_file_id: str = Field(min_length=1)
    decision_version: str = Field(min_length=1)
    decided_by: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1)


class NormalizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file_id: str = Field(min_length=1)
    mapping_id: str = Field(min_length=1)


class MatchingJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    normalization_ids: list[str] = Field(min_length=1)
    policy_version: str = Field(default="jan-candidate-v1", min_length=1)
    similarity_threshold: float = Field(default=0.85, ge=0, le=1)
    handoff_similarity_threshold: float = Field(default=0.6, ge=0, le=1)
    max_handoff_gap_days: int = Field(default=31, ge=0, le=366)

    @model_validator(mode="after")
    def validate_thresholds(self):
        if self.handoff_similarity_threshold > self.similarity_threshold:
            raise ValueError("handoff用類似度は通常類似度以下です")
        if len(set(self.normalization_ids)) != len(self.normalization_ids):
            raise ValueError("normalization_idsは重複できません")
        return self


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1)
    created_by: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1)


class DecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1)
    decision: Literal["SAME_PRODUCT", "DIFFERENT_PRODUCT", "SUCCESSOR", "UNRESOLVED"]
    left_product_id: str | None = None
    right_product_id: str | None = None
    mapping_version: str = Field(min_length=1)
    approved_by: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1)


class JanMappingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jan: str = Field(min_length=1)
    canonical_product_id: str = Field(min_length=1)
    valid_from: date
    valid_to: date | None = None
    mapping_version: str = Field(min_length=1)
    approved_by: str | None = Field(default=None, min_length=1)
    reason: str = Field(min_length=1)


class HandlingPeriodCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_product_id: str = Field(min_length=1)
    center_id: str = Field(min_length=1)
    valid_from: date
    valid_to: date | None = None
    status: Literal["CONFIRMED", "TENTATIVE"]
    period_version: str = Field(min_length=1)
    approved_by: str | None = Field(default=None, min_length=1)
    basis: str = Field(min_length=1)


class RunCreated(BaseModel):
    run_id: str
    status: str


class RunStatusOutput(BaseModel):
    run_id: str
    experiment_id: str
    status: str
    cancellation_requested: bool
    origin_counts: dict[str, int]
    failure_count: int
