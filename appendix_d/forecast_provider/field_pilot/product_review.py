"""現場原本から未確定の商品コードを抽出し、JAN確認画面へ渡す。"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from ..ingestion.processor import detect_stream_encoding
from ..inventory_foundation.domain import validate_jan
from ..mapping_dry_run.product_jan_candidates import build_product_jan_candidates
from .forecast_readiness import product_readiness

PRODUCT_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
REQUIRED_HEADERS = {"商品コード", "商品名", "明細倉庫コード", "明細バラ数"}
MAX_FILES = 5_000
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_ROWS = 5_000_000
MAX_PRODUCTS = 10_000
SHIPMENT_HEADERS = {"商品コード", "商品名", "JAN", "出荷日", "数量"}
SHIPMENT_DATE = re.compile(r"^\d{4}[/-]\d{2}[/-]\d{2}(?: \d{1,2}:\d{2}:\d{2})?$")


def _encoding(path: Path) -> str:
    with path.open("rb") as source:
        encoding, error = detect_stream_encoding(source)
    if error or encoding is None:
        raise ValueError("PRODUCT_REVIEW_ENCODING_UNKNOWN")
    return encoding


def unresolved_products(inbox_root: Path, settings_store) -> dict:
    """JAN未確認の商品だけ返す。原本行・数量は保存も返却もしない。"""

    archive = inbox_root / "Archive"
    if not archive.is_dir() or archive.is_symlink():
        return {"items": [], "unresolved_count": 0,
                "confirmed_items": [], "confirmed_count": 0, "file_count": 0,
                "skipped_file_count": 0,
                "complete": True}
    paths = sorted(archive.glob("*/*/*.csv"))
    root = archive.resolve(strict=True)
    if len(paths) > MAX_FILES:
        raise ValueError("PRODUCT_REVIEW_FILE_LIMIT")
    products: dict[str, set[str]] = defaultdict(set)
    shipments: list[tuple[Path, str]] = []
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
            encoding = _encoding(path)
            with path.open("r", encoding=encoding, errors="strict", newline="") as source:
                reader = csv.DictReader(source, strict=True)
                if SHIPMENT_HEADERS.issubset(reader.fieldnames or ()):
                    shipments.append((path, encoding))
                    continue
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
                        if len(products) >= MAX_PRODUCTS and code not in products:
                            raise ValueError("PRODUCT_REVIEW_PRODUCT_LIMIT")
                        if name:
                            products[code].add(name[:120])
                        else:
                            products.setdefault(code, set())
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).endswith("_LIMIT"):
                raise
            skipped += 1
    needed_names = {name for names in products.values() for name in names}
    confirmed = {
        code: record
        for code in products
        if (record := settings_store.current("JAN_MAPPING", code)) is not None
    }
    jans_by_name: dict[str, set[str]] = defaultdict(set)
    jans_by_code: dict[str, set[str]] = defaultdict(set)
    observed_days_by_jan: dict[str, set[date]] = defaultdict(set)
    conflicts: set[str] = set()
    confirmed_jans = {record["value"]["jan"] for record in confirmed.values()}
    for path, encoding in shipments:
        try:
            with path.open("r", encoding=encoding, errors="strict", newline="") as source:
                reader = csv.DictReader(source, strict=True)
                for row in reader:
                    rows_seen += 1
                    if rows_seen > MAX_ROWS:
                        raise ValueError("PRODUCT_REVIEW_ROW_LIMIT")
                    if None in row:
                        raise csv.Error("row shape")
                    code = (row.get("商品コード") or "").strip()
                    name = (row.get("商品名") or "").strip()
                    jan = (row.get("JAN") or "").strip()
                    try:
                        jan = validate_jan(jan)
                    except ValueError:
                        continue
                    if code in products:
                        jans_by_code[code].add(jan)
                    if code in confirmed:
                        if jan != confirmed[code]["value"]["jan"]:
                            conflicts.add(code)
                    if jan in confirmed_jans:
                        raw_date = (row.get("出荷日") or "").strip()
                        if not SHIPMENT_DATE.fullmatch(raw_date):
                            continue
                        try:
                            day = date.fromisoformat(raw_date[:10].replace("/", "-"))
                        except ValueError:
                            continue
                        observed_days_by_jan[jan].add(day)
                    if name in needed_names:
                        jans_by_name[name].add(jan)
        except (OSError, UnicodeError, csv.Error):
            skipped += 1
    items = []
    confirmed_items = []
    for candidate in build_product_jan_candidates(
        products, jans_by_name, jans_by_code,
    ):
        code = candidate.product_code
        if code in confirmed:
            confirmed_jan = confirmed[code]["value"]["jan"]
            days = len(observed_days_by_jan.get(confirmed_jan, set()))
            trial_setting = settings_store.current("SHIPMENT_TRIAL_POLICY", code)
            confirmed_items.append({
                "product_code": code,
                "jan": confirmed_jan,
                "observed_shipment_days": days,
                "evidence_status": (
                    "JAN_CONFLICT" if code in conflicts else
                    "SHIPMENT_HISTORY_MISSING" if days == 0 else
                    "HISTORY_REVIEW_REQUIRED" if days < 28 else
                    "HISTORY_PRESENT"
                ),
                "readiness": product_readiness(
                    confirmed=True, jan_conflict=code in conflicts,
                    observed_days=days, source_complete=skipped == 0,
                    trial_policy=trial_setting["value"] if trial_setting else None,
                ),
                "trial_policy": trial_setting["value"] if trial_setting else None,
            })
        else:
            items.append({
                "product_code": code,
                "product_name": candidate.display_name,
                "candidate_jans": list(candidate.candidate_jans),
                "candidate_status": candidate.status.value,
                "direct_code_match": candidate.unique_candidate_is_direct,
                "readiness": product_readiness(
                    confirmed=False, source_complete=skipped == 0,
                ),
            })
    return {
        "items": items,
        "unresolved_count": len(items),
        "confirmed_items": confirmed_items,
        "confirmed_count": len(confirmed_items),
        "file_count": len(paths),
        "skipped_file_count": skipped,
        "complete": skipped == 0,
    }
