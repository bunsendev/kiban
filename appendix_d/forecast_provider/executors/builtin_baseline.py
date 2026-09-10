"""builtin-baseline用の固定学習executor。"""

from pathlib import Path

from ..catalog import CatalogStore
from ..jobs.contracts import RunStore
from ..providers.baseline_codec import BuiltinBaselineCodec
from ..providers.builtin_baseline import BuiltinBaselineProvider
from .fixed_provider import FixedProviderExecutor, _read_snapshot

__all__ = ["BuiltinBaselineExecutor", "_read_snapshot"]


class BuiltinBaselineExecutor(FixedProviderExecutor):
    def __init__(
        self, runs: RunStore, catalog: CatalogStore, artifact_root: Path, work_root: Path
    ) -> None:
        super().__init__(
            runs,
            catalog,
            artifact_root,
            work_root,
            BuiltinBaselineProvider,
            BuiltinBaselineCodec,
            "baseline-worker",
        )
