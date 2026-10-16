"""Review untrusted extraction evidence without inventing quantities or dates."""

import re
from datetime import date

EVIDENCE_FIELDS = (
    "source_region",
    "source_jan",
    "source_date",
    "source_expiry",
    "source_snapshot",
    "source_location",
    "source_kind",
    "source_quantity",
    "quantity_status",
)


def valid_jan(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}|[0-9]{13}", value):
        return False
    d = list(map(int, value))
    return (sum(d[-2::-2]) * 3 + sum(d[-3::-2]) + d[-1]) % 10 == 0


def explicit_date(value):
    match = re.search(
        r"(?<![0-9])([0-9]{4})[年/.-]([0-9]{1,2})[月/.-]([0-9]{1,2})(?:日)?(?![0-9])", value
    )
    if not match:
        return ""
    try:
        return date(*map(int, match.groups())).isoformat()
    except ValueError:
        return ""


def review(value, *, handwritten=False):
    result = {**value, "rows": [], "raw_rows": [dict(row) for row in value["rows"]]}
    warnings = []
    for original in value["rows"]:
        row = dict(original)
        issues = []
        jan = row.get("jan", "")
        if jan and not valid_jan(jan):
            row["source_jan"] = row.get("source_jan") or jan
            row["jan"] = ""
            issues.append("JAN候補を保留：" + jan + "（ラベル・桁数・チェック桁を確認）")
        if handwritten:
            raw_quantity = row.get("source_quantity", "")
            if row.get("quantity_status") != "clear" or re.search(
                r"[0-9]\s*[×*xX]\s*[0-9]", raw_quantity
            ):
                for key in ("quantity", "case_quantity", "loose_quantity", "units_per_case"):
                    if row.get(key):
                        row["source_ai_" + key] = row[key]
                        row[key] = ""
                issues.append(
                    "数量を保留：式・追記・単位の意味を確認してください（" + raw_quantity + "）"
                )
            for key in ("date", "expiry", "snapshot"):
                source = row.get("source_" + key, "")
                expected = explicit_date(source)
                if row.get(key) and row[key] != expected:
                    row["source_ai_" + key] = row[key]
                    row[key] = ""
                    issues.append(
                        key + "を保留：原記載に同じ年月日の根拠がありません（" + source + "）"
                    )
            if row.get("location") and row["location"] != row.get("source_location"):
                row["source_ai_location"] = row["location"]
                row["location"] = ""
                issues.append("倉庫を保留：原記載と照合してください")
            source_kind = row.get("source_kind", "")
            if row.get("kind") == "shipment" and (
                "出荷" not in source_kind and "当出" not in source_kind
            ):
                row["kind"] = "unknown"
                issues.append("出荷の根拠がありません。在庫／出荷を確認してください")
            if row.get("kind") == "shipment" and "在庫" in source_kind:
                row["kind"] = "unknown"
                issues.append("出荷と在庫の表記が混在しています。種類を確認してください")
            if (
                row.get("kind") == "inventory"
                and "在庫" not in source_kind
                and "現在" not in source_kind
            ):
                row["kind"] = "unknown"
                issues.append("在庫の根拠がありません。種類を確認してください")
        if issues:
            row["note"] = (row.get("note", "") + " ／ " + " ／ ".join(issues)).strip(" ／")
        result["rows"].append(row)
    if handwritten:
        regions = {r.get("source_region") for r in result["rows"]}
        for region, label in (("left", "左表"), ("right", "右表")):
            if region not in regions:
                warnings.append(label + "の明細がありません。欠落・空表か原本を確認してください")
        locations = {r.get("location") for r in result["rows"]}
        for label in value.get("warehouse_headers", []):
            if label and label not in locations:
                warnings.append("倉庫列「" + label + "」の明細がありません。原本を確認してください")
        if not value.get("left_complete") or not value.get("right_complete"):
            warnings.append("左右の表のどちらかに未取得部分があります")
        seen = set()
        for row in result["rows"]:
            signature = tuple(
                row.get(key, "")
                for key in (
                    "product_name",
                    "location",
                    "date",
                    "expiry",
                    "snapshot",
                    "quantity",
                    "case_quantity",
                    "loose_quantity",
                )
            )
            if signature in seen:
                warnings.append(
                    "同じ内容の明細があります。重複か別明細か確認してください（自動削除しません）"
                )
                break
            seen.add(signature)
        if warnings:
            result["complete"] = False
    result["quality_warnings"] = warnings
    return result
