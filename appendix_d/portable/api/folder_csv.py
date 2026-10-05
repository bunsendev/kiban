"""Snapshot loose CSV files into a deterministic, byte-preserving archive."""

import hashlib
import io
import zipfile

from .business_archive import MAX_ZIP_BYTES, ArchiveError


def bundle_csv(paths):
    if sum(path.stat().st_size for path in paths) > MAX_ZIP_BYTES:
        raise ArchiveError("CSVの合計が100 MBを超えています。投入するファイルを分けてください")
    output = io.BytesIO()
    originals = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            before = path.stat()
            raw = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise OSError("CSVをコピー中です。コピー完了後に再確認します")
            originals.append((path, hashlib.sha256(raw).hexdigest()))
            info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    return output.getvalue(), originals
