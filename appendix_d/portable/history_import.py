"""Historical ZIP study adapter; never registers inventory or formal actuals."""

import csv
import hashlib
import io
import zipfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from functools import lru_cache

import pandas as pd

from .api.business_archive import (
    MAX_ZIP_BYTES,
    _business_date,
    _center_and_file_date,
    _decode,
    _safe_members,
)
from .api.document_evidence import valid_jan
from .transfers import VERSION as MOVEMENT_VERSION
from .transfers import shipment_class


def read_history_archive(raw, *, unit="UNCONFIRMED", excluded_jans=(), excluded_prefixes=()):
    if not raw or len(raw) > MAX_ZIP_BYTES:
        raise ValueError("履歴ZIPは100 MiB以下です")
    if unit not in {"UNCONFIRMED", "CASE", "EACH"}:
        raise ValueError("履歴数量の単位を確認してください")
    data = {}
    conflicts = set()
    counts = Counter()
    sources = []
    code_jans = defaultdict(set)
    transfer_sources = []
    movement_totals = defaultdict(Decimal)
    unresolved_sources = []
    valid = lru_cache(None)(valid_jan)
    parse = lru_cache(None)(_business_date)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for member in _safe_members(archive):
            if member.is_dir():
                continue
            if not member.filename.lower().endswith(".csv"):
                counts["non_csv_files"] += 1
                continue
            body = archive.read(member)
            source_sha = hashlib.sha256(body).hexdigest()
            rows = csv.DictReader(io.StringIO(_decode(body)))
            if not {"出荷日", "JAN", "数量"} <= set(rows.fieldnames or ()):
                counts["non_shipment_csv_files"] += 1
                continue
            center, fileday = _center_and_file_date(member.filename)
            aggregate = defaultdict(Decimal)
            known = {}
            unresolved_count = 0
            for row in rows:
                counts["shipment_source_rows"] += 1
                jan = str(row.get("JAN") or "").strip()
                day = parse(str(row.get("出荷日") or ""))
                if None in row or not valid(jan):
                    counts["invalid_jan_or_shape_rows"] += 1
                    continue
                if day is None:
                    counts["invalid_date_rows"] += 1
                    continue
                if jan in excluded_jans or any(jan.startswith(p) for p in excluded_prefixes):
                    counts["excluded_rows"] += 1
                    continue
                try:
                    q = Decimal(str(row.get("数量") or "").strip())
                except InvalidOperation:
                    counts["invalid_quantity_rows"] += 1
                    continue
                if not q.is_finite() or q < 0:
                    counts["invalid_quantity_rows"] += 1
                    continue
                explicit = str(row.get("倉庫") or row.get("倉庫名") or "").strip()
                warehouse_code = str(row.get("倉庫コード") or "").strip()
                if explicit:
                    location = explicit
                elif "日時" in member.filename and center != "不明" and warehouse_code:
                    location = center + "::" + warehouse_code
                else:
                    counts["warehouse_unresolved_rows"] += 1
                    continue
                if q == 0:
                    counts["explicit_zero_rows"] += 1
                if fileday is not None and day != fileday:
                    counts["row_file_date_mismatch_rows"] += 1
                row_unit = str(row.get("単位") or unit).strip()
                if row_unit not in {"CASE", "EACH", "UNCONFIRMED"}:
                    counts["unit_unresolved_rows"] += 1
                    continue
                movement = shipment_class(row)
                counts["movement_" + movement.lower() + "_rows"] += 1
                movement_totals[(movement, jan, row_unit)] += q
                if movement == "UNRESOLVED":
                    unresolved_count += 1
                if movement in {"TRANSFER_OUT", "TRANSFER_IN"}:
                    transfer_sources.append({"sha256": source_sha, "row": rows.line_num,
                                             "transfer_id": row["transfer_id"],
                                             "classification": movement,
                                             "quantity": str(q), "unit": row_unit})
                    continue
                key = (jan, location, row_unit, day.isoformat())
                aggregate[key] += q
                known[key] = max(day, fileday or day).isoformat()
                code = str(row.get("商品コード") or "").strip()
                if code:
                    code_jans[(location, code)].add(jan)
            if unresolved_count:
                unresolved_sources.append({"sha256": source_sha, "filename": member.filename,
                                           "rows": unresolved_count})
            for key, q in aggregate.items():
                if key in data and data[key][2] != source_sha:
                    conflicts.add(key)
                    continue
                available = max(data[key][1], known[key]) if key in data else known[key]
                data[key] = (q, available, source_sha)
            sources.append(
                {
                    "sha256": source_sha,
                    "file_date": None if fileday is None else fileday.isoformat(),
                    "aggregated_rows": len(aggregate),
                }
            )
    records = []
    for (jan, location, row_unit, day), (q, known, _sha) in sorted(data.items()):
        if (jan, location, row_unit, day) in conflicts:
            continue
        records.append(
            {
                "unique_id": jan + "::" + location,
                "ds": day,
                "y": str(q),
                "known_at": known + "T23:59:59+09:00",
                "unit": row_unit,
                "jan": jan,
                "warehouse": location,
            }
        )
    if not records:
        raise ValueError("対応と数量を確認できる出荷CSVがありません")
    frame = pd.DataFrame(records)
    counts["conflicted_product_dates"] = len(conflicts)
    counts["product_code_multiple_jans"] = sum(len(v) > 1 for v in code_jans.values())
    counts["normalized_rows"] = len(records)
    provenance = {
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "counts": dict(counts),
        "availability_mode": "FILE_DATE_ASSUMED",
        "source_quantity_column": "数量",
        "unit_confirmed": unit != "UNCONFIRMED" and "UNCONFIRMED" not in set(frame["unit"]),
        "source_files": sources,
        "formal_approval": False,
        "movement_contract": MOVEMENT_VERSION,
        "transfer_exclusions": transfer_sources,
        "unresolved_movement_sources": unresolved_sources,
        "movement_source_totals": [
            {"classification": k[0], "product": k[1], "unit": k[2], "quantity": str(q)}
            for k, q in sorted(movement_totals.items())
        ],
        "unresolved_movement_policy": "RETAINED_NOT_CONFIRMED_CUSTOMER_DEMAND",
    }
    return frame, provenance
