"""TimesFM計測レポートの内容アドレス方式による保存。"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any


def canonical_json(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def condition_fingerprint(payload: dict[str, Any]) -> str:
    compact = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(compact).hexdigest()


def publish_report(payload: dict[str, Any], output_root: Path) -> tuple[str, str]:
    content = canonical_json(payload)
    checksum = hashlib.sha256(content).hexdigest()
    target = output_root.resolve() / "timesfm-benchmarks" / f"{checksum}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError("同じchecksumのTimesFM計測レポート内容が一致しません")
    else:
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, target)
    return target.as_uri(), checksum
