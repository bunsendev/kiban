"""CSVを格納したZIPを検証用入力rootへ安全に一括保存する。"""

from __future__ import annotations

import os
import shutil
import uuid
import zipfile
from collections.abc import AsyncIterable
from pathlib import Path, PurePosixPath

from ..ingestion.processor import DEFAULT_LIMITS, ImportLimits
from .uploads import MAX_UPLOAD_BYTES, SourceUploadError


class MappingDryRunBulkUploader:
    """ZIPを検査し、検査完了後に一つのbatchとして公開する。"""

    def __init__(
        self,
        input_root: Path | None,
        max_archive_bytes: int = MAX_UPLOAD_BYTES,
        limits: ImportLimits = DEFAULT_LIMITS,
    ):
        self.input_root = input_root
        self.max_archive_bytes = max_archive_bytes
        self.limits = limits

    async def save(
        self,
        filename: str,
        chunks: AsyncIterable[bytes],
        content_length: int | None = None,
    ) -> dict[str, object]:
        if Path(filename.strip()).suffix.lower() != ".zip":
            raise SourceUploadError("一括アップロードにはZIPファイルを選択してください")
        if content_length is not None and content_length > self.max_archive_bytes:
            raise SourceUploadError(self._archive_limit_message())
        root = self._writable_root()
        batch_id = uuid.uuid4().hex
        parent = root / "client-uploads"
        pending_dir = parent / f".{batch_id}.pending"
        destination = parent / batch_id
        archive_path = pending_dir / ".upload.zip"
        try:
            pending_dir.mkdir(parents=True, exist_ok=False)
            size = await self._write_archive(archive_path, chunks)
            paths, total = self._extract(archive_path, pending_dir)
            archive_path.unlink()
            os.replace(pending_dir, destination)
        except SourceUploadError:
            shutil.rmtree(pending_dir, ignore_errors=True)
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            shutil.rmtree(pending_dir, ignore_errors=True)
            raise SourceUploadError("ZIPを安全に展開できません") from exc
        prefix = destination.relative_to(root).as_posix()
        analysis_path = next(
            (path for path in paths if "出荷" in PurePosixPath(path).name),
            paths[0],
        )
        return {
            "batch_id": batch_id,
            "source_prefix": prefix,
            "first_source_path": f"{prefix}/{paths[0]}",
            "analysis_source_path": f"{prefix}/{analysis_path}",
            "file_count": len(paths),
            "archive_size_bytes": size,
            "expanded_size_bytes": total,
        }

    async def _write_archive(self, path: Path, chunks: AsyncIterable[bytes]) -> int:
        size = 0
        with path.open("xb") as stream:
            async for chunk in chunks:
                size += len(chunk)
                if size > self.max_archive_bytes:
                    raise SourceUploadError(self._archive_limit_message())
                stream.write(chunk)
        if size == 0:
            raise SourceUploadError("空のZIPはアップロードできません")
        return size

    def _extract(self, archive_path: Path, target: Path) -> tuple[list[str], int]:
        paths: list[str] = []
        names: set[str] = set()
        total = 0
        with zipfile.ZipFile(archive_path) as archive:
            entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            if not entries:
                raise SourceUploadError("ZIPにCSVがありません")
            if len(entries) > self.limits.max_files:
                raise SourceUploadError("ZIPのファイル数が上限を超えています")
            for entry in entries:
                path = PurePosixPath(entry.filename.replace("\\", "/"))
                logical = path.as_posix()
                folded = logical.casefold()
                if path.is_absolute() or ".." in path.parts or not path.name:
                    raise SourceUploadError("ZIPの展開先逸脱を検出しました")
                if path.suffix.lower() != ".csv":
                    raise SourceUploadError("ZIPにはCSVだけを格納してください")
                if entry.flag_bits & 1:
                    raise SourceUploadError("暗号化ZIPはアップロードできません")
                if folded in names:
                    raise SourceUploadError("ZIP内の同名衝突を検出しました")
                if entry.file_size > self.limits.max_file_bytes:
                    raise SourceUploadError("ZIP内ファイルが容量上限を超えています")
                total += entry.file_size
                if total > self.limits.max_total_bytes:
                    raise SourceUploadError("ZIPの展開後容量が上限を超えています")
                names.add(folded)
                paths.append(logical)
            for entry, logical in zip(entries, paths, strict=True):
                output = target.joinpath(*PurePosixPath(logical).parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(entry) as source, output.open("xb") as sink:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > entry.file_size or written > self.limits.max_file_bytes:
                            raise SourceUploadError("ZIP内ファイルの実容量が不正です")
                        sink.write(chunk)
                if written != entry.file_size:
                    raise SourceUploadError("ZIP内ファイルの実容量が不正です")
        return paths, total

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

    def _archive_limit_message(self) -> str:
        return f"ZIPは{self.max_archive_bytes:,} bytes以下にしてください"
