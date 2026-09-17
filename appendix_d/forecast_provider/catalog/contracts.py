"""dataset snapshotとexperimentの版付き永続契約。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_id: str
    format_version: int
    content_hash: str
    manifest: dict


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    format_version: int
    condition_fingerprint: str
    snapshot_id: str
    definition: dict


class CatalogStore(Protocol):
    def put_snapshot(self, record: SnapshotRecord) -> None: ...

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None: ...

    def list_snapshots(self, *, limit: int = 100) -> list[SnapshotRecord]: ...

    def put_experiment(self, record: ExperimentRecord) -> None: ...

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None: ...

    def list_experiments(
        self, *, snapshot_id: str | None = None, limit: int = 100
    ) -> list[ExperimentRecord]: ...
