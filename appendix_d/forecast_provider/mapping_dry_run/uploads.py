"""クライアントCSVを検証用入力rootへ安全に保存する。"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import AsyncIterable
from pathlib import Path

MAX_UPLOAD_BYTES = 100_000_000
MAX_FILENAME_CHARS = 120
_SAFE_FILENAME = re.compile(r"^[^/\\\x00-\x1f\x7f]+$")
_WINDOWS_INVALID = frozenset('<>:"|?*')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class SourceUploadError(ValueError):
    """upload入力または保存先が契約を満たさない。"""


class MappingDryRunSourceUploader:
    """新規専用directoryへ保存し、既存ファイルを上書きしない。"""

    def __init__(self, input_root: Path | None, max_bytes: int = MAX_UPLOAD_BYTES):
        self.input_root = input_root
        self.max_bytes = max_bytes

    async def save(
        self,
        filename: str,
        chunks: AsyncIterable[bytes],
        content_length: int | None = None,
    ) -> dict[str, object]:
        safe_name = _validate_filename(filename)
        if content_length is not None and content_length > self.max_bytes:
            raise SourceUploadError(self._limit_message())
        root = self._writable_root()
        upload_id = uuid.uuid4().hex
        upload_dir = root / "client-uploads" / upload_id
        pending = upload_dir / ".pending"
        destination = upload_dir / safe_name
        try:
            upload_dir.mkdir(parents=True, exist_ok=False)
            size = 0
            with pending.open("xb") as stream:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise SourceUploadError(self._limit_message())
                    stream.write(chunk)
            if size == 0:
                raise SourceUploadError("空のCSVはアップロードできません")
            os.replace(pending, destination)
        except SourceUploadError:
            _remove_partial(pending, upload_dir)
            raise
        except OSError as exc:
            _remove_partial(pending, upload_dir)
            raise SourceUploadError("アップロード先に保存できません") from exc
        return {
            "source_path": destination.relative_to(root).as_posix(),
            "filename": safe_name,
            "size_bytes": size,
        }

    def _writable_root(self) -> Path:
        if self.input_root is None:
            raise SourceUploadError("アップロード先が設定されていません")
        try:
            root = self.input_root.resolve(strict=True)
        except OSError as exc:
            raise SourceUploadError("アップロード先を使用できません") from exc
        if not root.is_dir() or not os.access(root, os.R_OK | os.W_OK):
            raise SourceUploadError("アップロード先を使用できません")
        return root

    def _limit_message(self) -> str:
        return f"CSVは{self.max_bytes:,} bytes以下にしてください"


def _validate_filename(filename: str) -> str:
    value = filename.strip()
    stem = Path(value).stem.upper()
    if (
        not value
        or len(value) > MAX_FILENAME_CHARS
        or not _SAFE_FILENAME.fullmatch(value)
        or any(character in value for character in _WINDOWS_INVALID)
        or value.endswith((".", " "))
        or Path(value).suffix.lower() != ".csv"
        or stem in _WINDOWS_RESERVED
        or value in {".", ".."}
    ):
        raise SourceUploadError("ファイル名は120文字以下のCSV名にしてください")
    return value


def _remove_partial(pending: Path, upload_dir: Path) -> None:
    pending.unlink(missing_ok=True)
    try:
        upload_dir.rmdir()
    except OSError:
        pass
    try:
        upload_dir.parent.rmdir()
    except OSError:
        pass
