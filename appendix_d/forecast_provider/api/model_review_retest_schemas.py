"""レビュー対応の追加テスト実行入力。"""

from pydantic import BaseModel, ConfigDict, Field


class ReviewRetestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    expected_revision: int = Field(ge=1)
    target_snapshot_id: str = Field(min_length=1, max_length=200)
