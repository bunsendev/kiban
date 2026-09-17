"""比較キャンペーンAPIの入力schema。"""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CampaignModelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)


class ComparisonCampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    snapshot_id: str = Field(min_length=1)
    models: list[CampaignModelInput] = Field(min_length=2, max_length=12)
    purpose: str = Field(min_length=1, max_length=500)
    mode: str = Field(default="primary", pattern=r"^(primary|horizon)$")
    horizon: int | None = Field(default=None, ge=1, le=400)
    policy_version: str = Field(default="evaluation-v2.9", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_models(self):
        values = [(item.provider_id, item.model_id) for item in self.models]
        if len(values) != len(set(values)):
            raise ValueError("同じProvider・モデルは重複して選択できません")
        if self.mode == "horizon" and self.horizon is None:
            raise ValueError("horizon評価ではhorizonが必要です")
        if self.mode == "primary" and self.horizon is not None:
            raise ValueError("主評価期間ではhorizonを指定できません")
        return self
