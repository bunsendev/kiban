"""Conservative adapter for the printed inventory movement table, not scanned OCR."""

import re

from .document_ai import FIELDS, DocumentError
from .document_inventory_checks import inventory_checks, movement_check
from .document_pages import page_source, pdf_reader


def apply_current_blank_zero(row):
    """Normalize current inventory only; keep the original cells for comparison."""
    row["source_current_case"] = row["case_quantity"]
    row["source_current_loose"] = row["loose_quantity"]
    empty = not row["case_quantity"] and not row["loose_quantity"]
    row["case_quantity"] = row["case_quantity"] or "0"
    row["loose_quantity"] = row["loose_quantity"] or "0"
    if empty:
        row.update(exclude=True, reason="この帳票の現在両欄の空欄を0として除外（担当者指定）")
    row["note"] += " 担当者指定：現在欄の空欄は0。元の空欄は抽出履歴に保持。"


def extract_inventory(raw, *, blank_current_zero=False):
    count = len(pdf_reader(raw).pages)
    rows = []
    movements = []
    complete = True
    coverage = []
    for number in range(1, count + 1):
        _, text, _ = page_source(raw, number)
        lines = text.splitlines()
        header = next((s for s in lines if s.count("ケース") == 5 and s.count("バラ") == 5), "")
        if not header or "在庫集計日" not in text or "現在" not in text:
            raise DocumentError("このPDFは印刷在庫表の形式ではありません。AI読取を使用してください")
        cases = list(re.finditer("ケース", header))[-1].start()
        loose = list(re.finditer("バラ", header))[-1].start()
        case_columns = [m.start() for m in re.finditer("ケース", header)]
        loose_columns = [m.start() for m in re.finditer("バラ", header)]
        snapshot = re.search(r"在庫集計日[：:]\s*(\d{4})/(\d{2})/(\d{2})", text)
        warehouse = re.search(r"㈱ムロオ\s*(\S+)", text)
        anchors = [i for i, s in enumerate(lines)
                   if re.match(r"^\s*[0-9]{6,13}\s+", s)]
        recognized = []
        for index, line in enumerate(lines):
            jan = re.match(r"^\s*([0-9]{13})\s+", line)
            if not jan:
                continue
            recognized.append(index)
            expiry = re.search(r"\b(\d{2})/(\d{2})/(\d{2})\b", line[:cases])
            if not expiry:
                complete = False
            before = line[jan.end() : expiry.start() if expiry else cases].strip()
            pack = re.search(r"\s+(\d+)\s*$", before)
            detail_date = re.fullmatch(
                r"\s*\((\d{4})/(\d{2})/(\d{2})\)\s*",
                lines[index + 1] if index + 1 < len(lines) else "",
            )
            row = dict.fromkeys(FIELDS, "")
            row.update(
                source_adjustment_case=line[case_columns[3]:loose_columns[3]].strip(),
                source_adjustment_loose=line[loose_columns[3]:cases].strip(),
                source_detail_date="-".join(detail_date.groups()) if detail_date else "",
                kind="inventory",
                jan=jan[1],
                page=str(number),
                product_name=before[: pack.start()].strip() if pack else before,
                unit="現在ケース / 現在バラ",
                case_quantity=line[cases:loose].strip().replace(",", ""),
                loose_quantity=line[loose:].strip().replace(",", ""),
                units_per_case=pack[1] if pack else "",
                snapshot="-".join(snapshot.groups()) if snapshot else "",
                expiry="20" + "-".join(expiry.groups()) if expiry else "",
                location=warehouse[1] if warehouse else "",
                note="PDF埋込文字と現在欄から抽出。原本照合必須。空欄は未確認。C入は換算候補。",
            )
            if any(
                v and not re.fullmatch(r"[0-9]+", v)
                for v in (row["case_quantity"], row["loose_quantity"], row["units_per_case"])
            ):
                complete = False
                row["note"] += " 数量欄に判読不能部分があります。"
            if blank_current_zero:
                apply_current_blank_zero(row)
            movements.append(movement_check(line, case_columns, loose_columns, row))
            if row["source_adjustment_case"] or row["source_adjustment_loose"]:
                row["note"] += (
                    " 調整欄あり：現在欄を使用し、調整を再加算しません。"
                    "原本の調整理由は業務確認が必要です。"
                )
            rows.append(row)
            # The movement report's 当出 is the day's shipment, never 当入.
            # Business-confirmed policy for this printed report's outbound cells only.
            if "当出" in text and snapshot:
                out_cases = line[case_columns[2]:loose_columns[2]].strip().replace(",", "")
                out_loose = line[loose_columns[2]:case_columns[3]].strip().replace(",", "")
                shipped = dict(row)
                shipped.update(
                    kind="shipment", date=row["snapshot"], snapshot="", expiry="",
                    case_quantity=out_cases or "0", loose_quantity=out_loose or "0",
                    source_outbound_case=out_cases, source_outbound_loose=out_loose,
                    unit="当出ケース / 当出バラ", exclude=False, reason="",
                    note="PDF当出欄。担当者指定：当出の空欄は0。原本の空欄を履歴に保持。出荷日は在庫集計日。",
                )
                if any(v and not re.fullmatch(r"[0-9]+", v) for v in (out_cases, out_loose)):
                    complete = False
                rows.append(shipped)
        missed = sorted(set(anchors) - set(recognized))
        coverage.append({"page": number, "candidate_rows": len(anchors),
                         "recognized_rows": len(recognized),
                         "unparsed_lines": [i + 1 for i in missed]})
        if missed:
            complete = False
    if not rows or len(rows) > 1000:
        raise DocumentError("在庫明細を取得できないか1000行を超えています")
    return {
        "complete": complete,
        "rows": rows,
        "page_count": count,
        "pages_read": list(range(1, count + 1)),
        "model": "printed-inventory-movement-v3",
        "inventory_checks": inventory_checks(rows, movements),
        "coverage": {"version": "printed-row-anchors-v1", "pages": coverage,
                     "matched": all(p["candidate_rows"] == p["recognized_rows"] for p in coverage),
                     "basis": "文字層の行構造点検。実測正解率・原本全行の保証ではありません"},
        "blank_outbound_policy": "PRINTED_REPORT_OUTBOUND_BLANK_ZERO",
        "blank_current_policy": (
            "CURRENT_BLANK_ZERO_EXCLUDE_EMPTY" if blank_current_zero else "UNKNOWN"
        ),
    }
