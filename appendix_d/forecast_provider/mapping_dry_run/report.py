"""原値を含まないmappingドライラン証跡を原子的に保存する。"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any


def fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def publish_report(payload: dict[str, Any], output_root: Path) -> tuple[str, str]:
    content = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    checksum = hashlib.sha256(content).hexdigest()
    target = output_root.resolve() / "mapping-dry-run" / f"{checksum}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError("同じchecksumのmappingドライラン証跡内容が一致しません")
    else:
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, target)
    return target.as_uri(), checksum
