"""Public Releaseへ置く前に、公開禁止物を機械的に遮断する。"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path, PurePosixPath

MAX_PACKAGE_BYTES = 1_000_000_000
MAX_ENTRY_BYTES = 500_000_000
MAX_ENTRIES = 10_000
ALLOWED_SUFFIXES = {".exe", ".dll", ".so", ".pyd", ".bin", ".dat", ".png", ".ico"}
DENIED_COMPONENTS = {
    "source", "src", "tests", "secrets", "config", "learning", "inbox",
    "outbox", "backup", "logs", ".git", ".github", "__pycache__",
}
SENSITIVE = re.compile(
    rb"(?:ghp_|github_pat_|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


def inspect_public_package(package: Path) -> dict:
    if (package.is_symlink() or not package.is_file()
            or not 0 < package.stat().st_size <= MAX_PACKAGE_BYTES):
        raise ValueError("PUBLIC_PACKAGE_INVALID")
    count = total = 0
    try:
        with zipfile.ZipFile(package) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_ENTRIES:
                raise ValueError("PUBLIC_PACKAGE_ENTRY_LIMIT")
            seen = set()
            for entry in entries:
                name = PurePosixPath(entry.filename)
                if (entry.is_dir() or name.is_absolute() or ".." in name.parts
                        or "\\" in entry.filename or entry.filename in seen
                        or name.suffix.lower() not in ALLOWED_SUFFIXES
                        or any(part.lower() in DENIED_COMPONENTS for part in name.parts)
                        or entry.file_size > MAX_ENTRY_BYTES
                        or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("PUBLIC_PACKAGE_FORBIDDEN_CONTENT")
                seen.add(entry.filename)
                count += 1
                total += entry.file_size
                if total > MAX_PACKAGE_BYTES:
                    raise ValueError("PUBLIC_PACKAGE_UNCOMPRESSED_LIMIT")
                with archive.open(entry) as source:
                    previous = b""
                    while chunk := source.read(1024 * 1024):
                        if SENSITIVE.search(previous + chunk):
                            raise ValueError("PUBLIC_PACKAGE_SECRET_PATTERN")
                        previous = chunk[-100:]
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("PUBLIC_PACKAGE_INVALID") from exc
    return {"entry_count": count, "uncompressed_bytes": total}
