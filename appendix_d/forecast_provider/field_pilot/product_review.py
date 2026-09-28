"""現場原本から未確定の商品コードを抽出し、JAN確認画面へ渡す。"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from ..ingestion.processor import detect_stream_encoding

PRODUCT_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
REQUIRED_HEADERS = {"商品コード", "商品名", "明細倉庫コード", "明細バラ数"}
MAX_FILES = 5_000
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_ROWS = 5_000_000


def unresolved_products(inbox_root: Path, settings_store) -> dict:
    """JAN未確認の商品だけ返す。原本行・数量は保存も返却もしない。"""

    archive = inbox_root / "Archive"
    if not archive.is_dir() or archive.is_symlink():
        return {"items": [], "unresolved_count": 0, "file_count": 0,
                "skipped_file_count": 0,
                "complete": True}
    paths = sorted(archive.glob("*/*/*.csv"))
    root = archive.resolve(strict=True)
    if len(paths) > MAX_FILES:
        raise ValueError("PRODUCT_REVIEW_FILE_LIMIT")
    products: dict[str, str] = {}
    skipped = rows_seen = 0
    for path in paths:
        if (path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink()
                or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES):
            skipped += 1
            continue
        try:
            path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError):
            skipped += 1
            continue
        try:
            with path.open("rb") as source:
                encoding, error = detect_stream_encoding(source)
            if error or encoding is None:
                skipped += 1
                continue
            with path.open("r", encoding=encoding, errors="strict", newline="") as source:
                reader = csv.DictReader(source, strict=True)
                if not REQUIRED_HEADERS.issubset(reader.fieldnames or ()):
                    continue
                for row in reader:
                    rows_seen += 1
                    if rows_seen > MAX_ROWS:
                        raise ValueError("PRODUCT_REVIEW_ROW_LIMIT")
                    if None in row:
                        raise csv.Error("row shape")
                    code = (row.get("商品コード") or "").strip()
                    name = (row.get("商品名") or "").strip()
                    if PRODUCT_CODE.fullmatch(code):
                        products.setdefault(code, name[:120])
        except (OSError, UnicodeError, csv.Error):
            skipped += 1
    items = []
    for code, name in sorted(products.items()):
        if settings_store.current("JAN_MAPPING", code) is None:
            items.append({"product_code": code, "product_name": name})
    return {
        "items": items,
        "unresolved_count": len(items),
        "file_count": len(paths),
        "skipped_file_count": skipped,
        "complete": skipped == 0,
    }
