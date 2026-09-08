"""予測stateの保存契約。Codecは呼出側から明示的に登録する。"""

from .contracts import ArtifactError, ArtifactRef, ArtifactStorageError, ArtifactStore, StateCodec
from .local import LocalArtifactStore
from .repository import ForecastArtifactRepository

__all__ = [
    "ArtifactError",
    "ArtifactRef",
    "ArtifactStorageError",
    "ArtifactStore",
    "ForecastArtifactRepository",
    "LocalArtifactStore",
    "StateCodec",
]
