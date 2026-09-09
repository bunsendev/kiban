"""原本を検査し、内容アドレス方式で不変保存する。"""

import hashlib
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .contracts import ImportJob, SourceFile


@dataclass(frozen=True)
class ImportLimits:
    max_files: int = 5_000
    max_file_bytes: int = 100_000_000
    max_total_bytes: int = 2_000_000_000


DEFAULT_LIMITS = ImportLimits()


class ImportProcessor:
    def __init__(self, store, input_root: Path, archive_root: Path, limits=DEFAULT_LIMITS):
        self.store = store
        self.input_root = input_root.resolve()
        self.archive_root = archive_root.resolve()
        self.limits = limits

    def process_next(self) -> ImportJob | None:
        job = self.store.claim()
        if job is None:
            return None
        try:
            source = self._source(job.source_path)
            entries = self._entries(source)
            for logical_path, data in entries:
                self._record(job.import_id, logical_path, data)
            self.store.finish(job.import_id)
        except Exception as exc:
            self.store.finish(job.import_id, str(exc))
        return self.store.get_job(job.import_id)

    def _source(self, relative: str) -> Path:
        candidate = self.input_root / relative
        if candidate.is_symlink():
            raise ValueError("symbolic linkは取込できません")
        source = candidate.resolve()
        if source != self.input_root and self.input_root not in source.parents:
            raise ValueError("取込元が許可領域外です")
        if not source.exists():
            raise ValueError("取込元が見つかりません")
        return source

    def _entries(self, source: Path) -> list[tuple[str, bytes]]:
        if source.is_dir():
            paths = sorted(path for path in source.rglob("*") if path.is_file())
            if any(path.is_symlink() for path in paths):
                raise ValueError("symbolic linkは取込できません")
            if len(paths) > self.limits.max_files:
                raise ValueError("ファイル数が上限を超えています")
            if any(path.stat().st_size > self.limits.max_file_bytes for path in paths):
                raise ValueError("ファイル容量が上限を超えています")
            if sum(path.stat().st_size for path in paths) > self.limits.max_total_bytes:
                raise ValueError("総容量が上限を超えています")
            logical_paths = [path.relative_to(source).as_posix() for path in paths]
            if len({path.casefold() for path in logical_paths}) != len(logical_paths):
                raise ValueError("同名衝突を検出しました")
            items = [(path.relative_to(source).as_posix(), path.read_bytes()) for path in paths]
        elif zipfile.is_zipfile(source):
            items = self._zip_entries(source)
        else:
            items = [(source.name, source.read_bytes())]
        self._validate_limits(items)
        return items

    def _zip_entries(self, source: Path) -> list[tuple[str, bytes]]:
        items = []
        names = set()
        with zipfile.ZipFile(source) as archive:
            files = [info for info in archive.infolist() if not info.is_dir()]
            if len(files) > self.limits.max_files:
                raise ValueError("ZIPのファイル数が上限を超えています")
            if sum(info.file_size for info in files) > self.limits.max_total_bytes:
                raise ValueError("ZIPの展開後容量が上限を超えています")
            for info in files:
                path = PurePosixPath(info.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("ZIPの展開先逸脱を検出しました")
                logical = path.as_posix()
                folded = logical.casefold()
                if folded in names:
                    raise ValueError("ZIP内の同名衝突を検出しました")
                names.add(folded)
                if info.file_size > self.limits.max_file_bytes:
                    raise ValueError("ZIP内ファイルが容量上限を超えています")
                items.append((logical, archive.read(info)))
        return items

    def _validate_limits(self, items):
        if len(items) > self.limits.max_files:
            raise ValueError("ファイル数上限を超えています")
        if any(len(data) > self.limits.max_file_bytes for _, data in items):
            raise ValueError("ファイル容量上限を超えています")
        if sum(len(data) for _, data in items) > self.limits.max_total_bytes:
            raise ValueError("合計容量上限を超えています")

    def _record(self, import_id: str, logical_path: str, data: bytes):
        digest = hashlib.sha256(data).hexdigest()
        duplicate = self.store.find_hash(digest)
        previous = self.store.find_logical(logical_path)
        encoding, error = _strict_encoding(data)
        status = (
            "QUARANTINED"
            if error
            else "DUPLICATE"
            if duplicate
            else "CORRECTION_CANDIDATE"
            if previous
            else "ACCEPTED"
        )
        stored = None
        duplicate_of = duplicate[0] if duplicate else None
        correction_of = previous[0] if previous and not duplicate else None
        if status in {"ACCEPTED", "CORRECTION_CANDIDATE"}:
            target = self.archive_root / digest[:2] / digest
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                temporary = target.with_name(f".{uuid.uuid4().hex}.tmp")
                temporary.write_bytes(data)
                temporary.replace(target)
            elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("保存済み原本のchecksumが一致しません")
            stored = str(target)
        self.store.record_file(
            SourceFile(
                str(uuid.uuid4()),
                import_id,
                logical_path,
                len(data),
                digest,
                encoding,
                status,
                stored,
                duplicate_of,
                correction_of,
                error,
            )
        )


def _strict_encoding(data: bytes) -> tuple[str | None, str | None]:
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            text = data.decode(encoding, errors="strict")
            if "\ufffd" not in text:
                return encoding, None
        except UnicodeDecodeError:
            pass
    return None, "UTF-8/BOM付きUTF-8/CP932として厳密にdecodeできません"
