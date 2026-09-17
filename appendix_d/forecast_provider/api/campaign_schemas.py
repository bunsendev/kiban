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

    @model_validator(mode="after")
    def validate_models(self):
        values = [(item.provider_id, item.model_id) for item in self.models]
        if len(values) != len(set(values)):
            raise ValueError("同じProvider・モデルは重複して選択できません")
        return self
