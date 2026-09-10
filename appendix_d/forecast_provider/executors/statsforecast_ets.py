"""StatsForecast AutoETS用の固定学習executor。"""

from pathlib import Path

from ..catalog import CatalogStore
from ..jobs.contracts import RunStore
from ..providers.statsforecast_codec import StatsForecastETSCodec
from ..providers.statsforecast_ets import StatsForecastETSProvider
from .fixed_provider import FixedProviderExecutor


class StatsForecastETSExecutor(FixedProviderExecutor):
    def __init__(
        self, runs: RunStore, catalog: CatalogStore, artifact_root: Path, work_root: Path
    ) -> None:
        super().__init__(
            runs,
            catalog,
            artifact_root,
            work_root,
            StatsForecastETSProvider,
            StatsForecastETSCodec,
            "statsforecast-ets-worker",
        )
