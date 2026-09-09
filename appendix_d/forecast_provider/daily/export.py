"""日次値をchecksum付きの決定的CSVとして発行する。"""

import csv
import hashlib
import io
import os
import uuid
from pathlib import Path

from .contracts import DailyValue

HEADER = (
    "unique_id",
    "canonical_product_id",
    "center_id",
    "ds",
    "y",
    "daily_state",
    "available_at",
    "raw_quantity",
    "issue",
)


def publish_daily_csv(values: list[DailyValue], output_root: Path) -> tuple[str, str]:
    ordered = sorted(values, key=lambda item: (item.unique_id, item.ds))
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(HEADER)
    for item in ordered:
        writer.writerow(
            (
                item.unique_id,
                item.canonical_product_id,
                item.center_id,
                item.ds,
                "" if item.y is None else str(item.y),
                item.state,
                item.available_at,
                "" if item.raw_quantity is None else str(item.raw_quantity),
                item.issue or "",
            )
        )
    payload = stream.getvalue().encode("utf-8")
    checksum = hashlib.sha256(payload).hexdigest()
    target = output_root.resolve() / "daily" / f"{checksum}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != payload:
            raise ValueError("同じchecksumの出力内容が一致しません")
    else:
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    return target.as_uri(), checksum
