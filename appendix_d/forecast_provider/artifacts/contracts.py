"""保存先・Provider固有変換を差し替える契約。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

from ..contracts import ContextRef, ForecastDataset, ModelRef, ProviderConfig, ProviderMetadata
from ..errors import ContractViolationError
from ..run_context import RunContext


class ArtifactError(ContractViolationError):
    """保存形式・checksum・期待条件の不一致。通常の予測失敗へ変換しない。"""


class ArtifactStorageError(OSError):
    """保存先の読書き失敗。自動再試行は行わない。"""


@dataclass(frozen=True)
class ArtifactRef:
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ArtifactError("artifact sha256は小文字64桁hexです")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise ArtifactError("artifact size_bytesは正整数です")

    def to_dict(self) -> dict:
        return {"sha256": self.sha256, "size_bytes": self.size_bytes}

    @classmethod
    def from_dict(cls, value: dict) -> ArtifactRef:
        if not isinstance(value, dict) or set(value) != {"sha256", "size_bytes"}:
            raise ArtifactError("ArtifactRefのフィールド不一致")
        return cls(**value)


def reference_for(data: bytes) -> ArtifactRef:
    if not isinstance(data, bytes) or not data:
        raise ArtifactError("artifactは空でないbytesです")
    return ArtifactRef(hashlib.sha256(data).hexdigest(), len(data))


def verify_bytes(ref: ArtifactRef, data: bytes) -> None:
    if reference_for(data) != ref:
        raise ArtifactError("artifact checksum/size不一致")


class ArtifactStore(Protocol):
    def put(self, data: bytes) -> ArtifactRef:
        """完全な内容のみ公開する。同一内容は同一参照となり、既存内容を上書きしない。"""
        ...

    def get(self, ref: ArtifactRef) -> bytes:
        """参照の内容を読み込む。呼出側もchecksumを検証する。"""
        ...


class StateCodec(Protocol):
    codec_version: int

    def metadata(self) -> ProviderMetadata: ...

    def encode_model(
        self, model: ModelRef, dataset: ForecastDataset, config: ProviderConfig, context: RunContext
    ) -> dict: ...

    def decode_model(
        self,
        payload: dict,
        model: ModelRef,
        dataset: ForecastDataset,
        config: ProviderConfig,
        context: RunContext,
    ) -> ModelRef: ...

    def encode_context(self, ref: ContextRef, model: ModelRef) -> dict: ...

    def decode_context(self, payload: dict, ref: ContextRef, model: ModelRef) -> ContextRef: ...
