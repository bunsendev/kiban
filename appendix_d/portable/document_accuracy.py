"""Offline, reproducible field metrics against human-confirmed complete pages.

Row IDs must be mapped to original rows independently of prediction order.
No API calls, model training, business approval or source changes are performed.
"""

import argparse
import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = (
    "jan",
    "product_code",
    "product_name",
    "date",
    "snapshot",
    "source_detail_date",
    "expiry",
    "location",
    "case_quantity",
    "loose_quantity",
    "units_per_case",
    "unit",
)
NUMBERS = {"case_quantity", "loose_quantity", "units_per_case"}


def same(field, expected, actual):
    if not isinstance(expected, str) or not isinstance(actual, str):
        return False
    if expected == "" or actual == "" or field not in NUMBERS:
        return expected == actual
    try:
        a, b = Decimal(expected), Decimal(actual)
        return a.is_finite() and b.is_finite() and a == b
    except InvalidOperation:
        return False


def evaluate(truth, prediction):
    gold = truth.get("records", [])
    pages = truth.get("pages", [])
    if not gold or not pages:
        raise ValueError("担当者が原本全行を確認したページと正解明細が必要です")
    verified_pages = set()
    for page in pages:
        if page.get("all_rows_confirmed") is not True or not page.get("confirmed_by"):
            raise ValueError("原本全行の確認者と確認状態が必要です")
        verified_pages.add((page["source_sha256"], str(page["page"])))
    expected = {}
    for row in gold:
        if row.get("status") != "HUMAN_CONFIRMED" or not row.get("confirmed_by"):
            raise ValueError("未確認の候補を正解として使えません")
        if (row["source_sha256"], str(row["page"])) not in verified_pages:
            raise ValueError("原本ページの確認範囲が一致しません")
        if row["id"] in expected or not isinstance(row.get("confirmed_values"), dict):
            raise ValueError("正解行IDの重複または値の不正があります")
        expected[row["id"]] = row
    by_id = {}
    duplicates = 0
    automatic = wrong_automatic = unknown_automatic = 0
    for row in prediction.get("records", []):
        if (row["source_sha256"], str(row["page"])) not in verified_pages:
            raise ValueError("予測には未評価の原本ページが含まれます。範囲を分けてください")
        duplicate = row["id"] in by_id
        if duplicate:
            duplicates += 1
        else:
            by_id[row["id"]] = row
        gold_row = expected.get(row["id"])
        if gold_row and (row["source_sha256"], str(row["page"])) != (
            gold_row["source_sha256"],
            str(gold_row["page"]),
        ):
            raise ValueError("原本行IDと原本ページの対応が矛盾しています")
        values = row.get("predicted_values") or {}
        good = bool(gold_row) and not duplicate
        if good:
            good = all(
                same(f, gold_row["confirmed_values"].get(f), values.get(f))
                for f in FIELDS
                if f not in gold_row.get("unreadable_fields", [])
            )
        if row.get("classification") == "READY":
            automatic += 1
            if gold_row and gold_row.get("unreadable_fields"):
                unknown_automatic += 1
            else:
                wrong_automatic += not good
    metrics = {f: Counter(correct=0, evaluated=0, unreadable=0) for f in FIELDS}
    complete_rows = 0
    for key, row in expected.items():
        values = (by_id.get(key) or {}).get("predicted_values") or {}
        all_correct = key in by_id
        for field in FIELDS:
            if field in row.get("unreadable_fields", []):
                metrics[field]["unreadable"] += 1
                all_correct = False
                continue
            metrics[field]["evaluated"] += 1
            ok = same(field, row["confirmed_values"].get(field), values.get(field))
            metrics[field]["correct"] += ok
            all_correct &= ok
        complete_rows += all_correct
    matched = len(expected.keys() & by_id.keys())
    return {
        "format": "portable-document-accuracy-v1",
        "gold_rows": len(expected),
        "matched_rows": matched,
        "missing_rows": len(expected) - matched,
        "extra_rows": len(by_id.keys() - expected.keys()),
        "duplicate_predictions": duplicates,
        "complete_correct_rows": complete_rows,
        "fields": {k: dict(v) for k, v in metrics.items()},
        "automatic_candidates": automatic,
        "wrong_automatic_candidates": wrong_automatic,
        "unverifiable_automatic_candidates": unknown_automatic,
        "row_recall": matched / len(expected),
        "wrong_automatic_rate": wrong_automatic / (automatic - unknown_automatic)
        if automatic > unknown_automatic
        else None,
        "truth_hash": hashlib.sha256(json.dumps(truth, sort_keys=True).encode()).hexdigest(),
        "prediction_hash": hashlib.sha256(
            json.dumps(prediction, sort_keys=True).encode()
        ).hexdigest(),
        "notice": "自動処理候補の評価です。正式採用・学習済みの意味ではありません",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(
        json.loads(args.truth.read_text("utf-8")), json.loads(args.predictions.read_text("utf-8"))
    )
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("評価結果を保存しました（業務データの正式採用はしていません）")


if __name__ == "__main__":
    main()
