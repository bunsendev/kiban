"""適合試験証跡の内容アドレス保存。"""

import hashlib
import json
from pathlib import Path


def save_evidence(root: Path, value: dict) -> tuple[str, str]:
    content = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    checksum = hashlib.sha256(content).hexdigest()
    path = root / checksum[:2] / f"{checksum}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != content:
        raise ValueError("同一checksumの証跡内容が一致しません")
    if not path.exists():
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
    return path.resolve().as_uri(), checksum
