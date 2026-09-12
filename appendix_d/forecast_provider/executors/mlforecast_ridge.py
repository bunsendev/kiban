"""MLForecast Ridge用の固定学習executor。"""

from pathlib import Path

from ..catalog import CatalogStore
from ..jobs.contracts import RunStore
from ..providers.mlforecast_codec import MLForecastRidgeCodec
from ..providers.mlforecast_ridge import MLForecastRidgeProvider
from .fixed_provider import FixedProviderExecutor


class MLForecastRidgeExecutor(FixedProviderExecutor):
    def __init__(
        self, runs: RunStore, catalog: CatalogStore, artifact_root: Path, work_root: Path
    ) -> None:
        super().__init__(
            runs,
            catalog,
            artifact_root,
            work_root,
            MLForecastRidgeProvider,
            MLForecastRidgeCodec,
            "mlforecast-ridge-worker",
        )
