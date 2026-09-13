"""機密情報を含まない内容アドレス方式の訓練証跡。"""

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


def publish_report(payload: dict[str, Any], output_root: Path) -> tuple[Path, str]:
    content = canonical_json(payload)
    checksum = hashlib.sha256(content).hexdigest()
    target = output_root.resolve() / "postgres-recovery-drills" / f"{checksum}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError("同じchecksumのリカバリ訓練証跡内容が一致しません")
    else:
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, target)
    return target, checksum
