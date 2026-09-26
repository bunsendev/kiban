"""管理対象入力root内のCSVを、原値を返さずに一覧化する。"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from ..ingestion.processor import detect_encoding

HEADER_LIMIT_BYTES = 131_072
HEADER_LIMIT_COLUMNS = 200


def _safe_file(root: Path, candidate: Path) -> Path | None:
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_file() and root in resolved.parents else None


def _header(path: Path) -> tuple[str | None, list[str], str | None]:
    try:
        with path.open("rb") as stream:
            data = stream.readline(HEADER_LIMIT_BYTES + 1)
    except OSError:
        return None, [], "READ_FAILED"
    if not data:
        return None, [], "EMPTY_FILE"
    if len(data) > HEADER_LIMIT_BYTES:
        return None, [], "HEADER_TOO_LARGE"
    encoding, error = detect_encoding(data)
    if error or encoding is None:
        return None, [], "ENCODING_UNSUPPORTED"
    try:
        row = next(csv.reader(data.decode(encoding).splitlines()), [])
    except (UnicodeDecodeError, csv.Error):
        return encoding, [], "HEADER_INVALID"
    if not row:
        return encoding, [], "HEADER_MISSING"
    if len(row) > HEADER_LIMIT_COLUMNS:
        return encoding, [], "TOO_MANY_COLUMNS"
    return encoding, row, None


class MappingDryRunSourceCatalog:
    """CSVの相対pathとヘッダーだけを返すread-only catalog。"""

    def __init__(self, input_root: Path | None):
        self.input_root = input_root

    def list_sources(self, limit: int = 200) -> dict:
        if self.input_root is None:
            return {"configured": False, "items": []}
        try:
            root = self.input_root.resolve(strict=True)
        except OSError:
            return {"configured": False, "items": []}
        if not root.is_dir():
            return {"configured": False, "items": []}
        items = []
        for candidate in sorted(root.rglob("*.csv"), key=lambda value: value.as_posix()):
            path = _safe_file(root, candidate)
            if path is None:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            encoding, columns, error = _header(path)
            items.append(
                {
                    "source_path": path.relative_to(root).as_posix(),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                    "encoding": encoding,
                    "columns": columns,
                    "header_error": error,
                }
            )
            if len(items) >= limit:
                break
        return {"configured": True, "items": items}

    def get_source(self, source_path: str) -> dict:
        """指定された相対pathだけを一覧と同じ安全条件で返す。"""
        if self.input_root is None:
            return {"configured": False, "items": []}
        try:
            root = self.input_root.resolve(strict=True)
        except OSError:
            return {"configured": False, "items": []}
        path = _safe_file(root, root / source_path)
        if path is None or path.suffix.lower() != ".csv":
            return {"configured": True, "items": []}
        try:
            stat = path.stat()
        except OSError:
            return {"configured": True, "items": []}
        encoding, columns, error = _header(path)
        return {
            "configured": True,
            "items": [
                {
                    "source_path": path.relative_to(root).as_posix(),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                    "encoding": encoding,
                    "columns": columns,
                    "header_error": error,
                }
            ],
        }

    def paths_under(self, source_prefix: str) -> list[str]:
        """安全な相対prefix直下にあるCSV pathを全件返す。"""
        if self.input_root is None:
            return []
        try:
            root = self.input_root.resolve(strict=True)
            prefix = (root / source_prefix).resolve(strict=True)
        except OSError:
            return []
        if prefix != root and root not in prefix.parents:
            return []
        if not prefix.is_dir() or prefix.is_symlink():
            return []
        paths = []
        for candidate in prefix.rglob("*.csv"):
            path = _safe_file(root, candidate)
            if path is not None:
                paths.append(path.relative_to(root).as_posix())
        return sorted(paths)
