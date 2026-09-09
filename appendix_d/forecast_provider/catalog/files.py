"""参照実装で許可するfile snapshot境界。"""

import hashlib
import os
from pathlib import Path
from urllib.parse import unquote, urlparse


def snapshot_path(uri: str, allowed_root: Path | None = None) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc:
        raise ValueError("参照実装はローカルfile URIだけを受理します")
    raw_path = unquote(parsed.path)
    if os.name == "nt" and len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    path = Path(raw_path).resolve()
    if allowed_root is not None and not path.is_relative_to(allowed_root.resolve()):
        raise ValueError("snapshotは許可されたroot内に配置してください")
    return path


def verify_snapshot_file(uri: str, expected_sha256: str, root: Path | None = None) -> Path:
    path = snapshot_path(uri, root)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("snapshot data checksum不一致")
    return path
