"""原本取込の永続契約。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ImportJob:
    import_id: str
    source_path: str
    status: str
    file_count: int = 0
    accepted_count: int = 0
    quarantined_count: int = 0
    duplicate_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class SourceFile:
    source_file_id: str
    import_id: str
    logical_path: str
    size_bytes: int
    sha256: str
    encoding: str | None
    status: str
    stored_path: str | None
    duplicate_of: str | None = None
    correction_of: str | None = None
    error: str | None = None


class IngestionStore(Protocol):
    def enqueue(self, source_path: str) -> ImportJob: ...
    def get_job(self, import_id: str) -> ImportJob | None: ...
    def claim(self) -> ImportJob | None: ...
    def record_file(self, value: SourceFile) -> None: ...
    def finish(self, import_id: str, error: str | None = None) -> None: ...
    def list_files(self, import_id: str) -> list[SourceFile]: ...
