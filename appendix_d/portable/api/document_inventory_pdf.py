"""Conservative adapter for the printed inventory movement table, not scanned OCR."""

import re

from .document_ai import FIELDS, DocumentError
from .document_pages import page_source, pdf_reader


def extract_inventory(raw):
    count = len(pdf_reader(raw).pages)
    rows = []
    complete = True
    for number in range(1, count + 1):
        _, text, _ = page_source(raw, number)
        lines = text.splitlines()
        header = next((s for s in lines if s.count("ケース") == 5 and s.count("バラ") == 5), "")
        if not header or "在庫集計日" not in text or "現在" not in text:
            raise DocumentError("このPDFは印刷在庫表の形式ではありません。AI読取を使用してください")
        cases = list(re.finditer("ケース", header))[-1].start()
        loose = list(re.finditer("バラ", header))[-1].start()
        snapshot = re.search(r"在庫集計日[：:]\s*(\d{4})/(\d{2})/(\d{2})", text)
        warehouse = re.search(r"㈱ムロオ\s*(\S+)", text)
        for line in lines:
            jan = re.match(r"^\s*([0-9]{13})\s+", line)
            if not jan:
                continue
            expiry = re.search(r"\b(\d{2})/(\d{2})/(\d{2})\b", line[:cases])
            if not expiry:
                complete = False
            before = line[jan.end() : expiry.start() if expiry else cases].strip()
            pack = re.search(r"\s+(\d+)\s*$", before)
            row = dict.fromkeys(FIELDS, "")
            row.update(
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
            rows.append(row)
    if not rows or len(rows) > 1000:
        raise DocumentError("在庫明細を取得できないか1000行を超えています")
    return {
        "complete": complete,
        "rows": rows,
        "page_count": count,
        "pages_read": list(range(1, count + 1)),
        "model": "printed-inventory-v1",
    }
