"""Read-only diagnostics for native movement reports, never business approval."""

import re
from collections import defaultdict
from datetime import date

from .document_evidence import valid_jan


def movement_check(line, case_columns, loose_columns, row):
    cells = [
        [
            line[start:loose_columns[i]].strip().replace(",", ""),
            line[loose_columns[i]:case_columns[i + 1] if i < 4 else len(line)]
            .strip().replace(",", ""),
        ]
        for i, start in enumerate(case_columns)
    ]
    result = {
        "page": row["page"], "jan": row["jan"], "cells": cells,
        "status": "unverifiable", "difference": None,
    }
    pack = str(row.get("units_per_case") or "")
    if (
        not re.fullmatch(r"[0-9]{1,6}", pack)
        or int(pack) <= 0
        or any(v and not re.fullmatch(r"-?[0-9]{1,15}", v) for pair in cells for v in pair)
    ):
        return result
    amounts = [int(a or 0) * int(pack) + int(b or 0) for a, b in cells]
    difference = amounts[0] + amounts[1] - amounts[2] + amounts[3] - amounts[4]
    result.update(status="match" if difference == 0 else "mismatch", difference=difference)
    return result


def inventory_checks(rows, movement_rows):
    inventories = [r for r in rows if r.get("kind") == "inventory"]
    groups = defaultdict(list)
    issues = []
    for index, row in enumerate(inventories, 1):
        fields = []
        if not valid_jan(str(row.get("jan") or "")):
            fields.append("JAN")
        for key in ("snapshot", "expiry", "source_detail_date"):
            try:
                date.fromisoformat(row.get(key) or "")
            except (ValueError, TypeError):
                fields.append(key)
        for key in ("product_name", "location"):
            if not str(row.get(key) or "").strip():
                fields.append(key)
        if fields:
            issues.append({"row": index, "page": row.get("page"),
                           "jan": row.get("jan"), "fields": fields})
        key = tuple(row.get(k) or "" for k in (
            "jan", "location", "snapshot", "expiry", "source_detail_date"
        ))
        if all(key):
            groups[key].append({"row": index, "page": row.get("page")})
    return {
        "version": "printed-inventory-checks-v1",
        "basis": "原本読取時の点検。編集後の再判定・担当者の承認ではありません。",
        "assumption": "数量収支は空欄=0・C入を換算係数と仮定した診断です。単位を確定しません。",
        "inventory_rows": len(inventories),
        "match": sum(r["status"] == "match" for r in movement_rows),
        "mismatch": sum(r["status"] == "mismatch" for r in movement_rows),
        "unverifiable": sum(r["status"] == "unverifiable" for r in movement_rows),
        "unchecked": max(0, len(inventories) - len(movement_rows)),
        "movement_rows": movement_rows,
        "field_issues": issues,
        "repeated_buckets": [
            {"jan": k[0], "location": k[1], "snapshot": k[2], "expiry": k[3],
             "receipt_date": k[4], "rows": value}
            for k, value in groups.items() if len(value) > 1
        ],
    }
