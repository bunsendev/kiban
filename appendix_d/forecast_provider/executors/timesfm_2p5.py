"""TimesFM 2.5用のzero-shot executor。"""

from pathlib import Path

from ..catalog import CatalogStore
from ..jobs.contracts import RunStore
from ..providers.timesfm_2p5 import TimesFM2p5Provider
from ..providers.timesfm_codec import TimesFM2p5Codec
from .fixed_provider import FixedProviderExecutor


class TimesFM2p5Executor(FixedProviderExecutor):
    def __init__(
        self, runs: RunStore, catalog: CatalogStore, artifact_root: Path, work_root: Path
    ) -> None:
        super().__init__(
            runs,
            catalog,
            artifact_root,
            work_root,
            TimesFM2p5Provider,
            TimesFM2p5Codec,
            "timesfm-2p5-worker",
        )
