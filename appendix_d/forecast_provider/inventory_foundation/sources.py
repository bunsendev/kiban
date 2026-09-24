"""inventory snapshot Workerが利用する原本読取境界。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .job_contracts import InventorySnapshotJobErrorCode


class InventorySourceReadError(RuntimeError):
    def __init__(self, code: InventorySnapshotJobErrorCode):
        self.code = code
        super().__init__(code.value)


class InventorySourceReader(Protocol):
    def read(self, source_reference: str) -> bytes: ...


class DirectoryInventorySourceReader:
    """固定root内の相対参照だけを読み、pathを例外へ出さない。"""

    def __init__(self, root: Path, *, max_bytes: int = 100 * 1024 * 1024):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir() or max_bytes < 1:
            raise ValueError("有効なsource rootと正のmax_bytesが必要です")
        self.max_bytes = max_bytes

    def read(self, source_reference: str) -> bytes:
        reference = Path(source_reference)
        if reference.is_absolute() or not reference.parts or ".." in reference.parts:
            raise InventorySourceReadError(
                InventorySnapshotJobErrorCode.SOURCE_REFERENCE_INVALID
            )
        try:
            target = (self.root / reference).resolve(strict=True)
            target.relative_to(self.root)
        except (FileNotFoundError, OSError, ValueError):
            raise InventorySourceReadError(InventorySnapshotJobErrorCode.SOURCE_NOT_FOUND) from None
        if not target.is_file():
            raise InventorySourceReadError(InventorySnapshotJobErrorCode.SOURCE_NOT_FOUND)
        try:
            if target.stat().st_size > self.max_bytes:
                raise InventorySourceReadError(InventorySnapshotJobErrorCode.SOURCE_TOO_LARGE)
            return target.read_bytes()
        except InventorySourceReadError:
            raise
        except OSError:
            raise InventorySourceReadError(InventorySnapshotJobErrorCode.SOURCE_NOT_FOUND) from None
