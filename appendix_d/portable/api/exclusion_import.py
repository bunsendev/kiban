"""Review-only exclusion list adapters; no automatic registration."""

import csv
import hashlib
import io
import json
import re
from pathlib import Path

from portable.runtime.ai_usage import AiUsage
from portable.runtime.api_credentials import ApiCredentials

from .document_ai import MAX_BYTES, DocumentError, extract
from .document_inventory_pdf import extract_inventory
from .document_suggestions import suggest_rows


def valid_jan(value):
    if not re.fullmatch(r"[0-9]{13}", value):
        return False
    d = list(map(int, value))
    return (sum(d[-2::-2]) * 3 + sum(d[-3::-2]) + d[-1]) % 10 == 0


def preview_list(raw, name, paths, *, consent=False, master=None):
    try:
        return _preview_list(raw, name, paths, consent=consent, master=master)
    except csv.Error:
        raise DocumentError("CSVの引用符・列構成を確認してください") from None


def _preview_list(raw, name, paths, *, consent=False, master=None):
    if not raw or len(raw) > MAX_BYTES:
        raise DocumentError("10 MB以内の除外リストを選んでください")
    suffix = Path(name).suffix.lower()
    complete = True
    method = "local"
    if suffix == ".json":
        try:
            value = json.loads(raw)
            if value.get("format") != "bunsen-product-exclusions-v1":
                raise ValueError()
            rows = value["products"]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise DocumentError("除外リストJSONの形式を確認してください") from None
    elif suffix == ".csv":
        text = None
        for encoding in ("utf-8-sig", "cp932"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise DocumentError("CSVはUTF-8またはCP932で保存してください")
        reader = csv.DictReader(io.StringIO(text), strict=True)
        columns = reader.fieldnames or []
        if not any(k in columns for k in ("JAN", "JANコード", "jan", "商品名", "product_name")):
            raise DocumentError("CSVにはJANまたは商品名の見出しが必要です")
        rows = []
        for row in reader:
            if len(rows) >= 1000:
                raise DocumentError("除外リストは1000明細以内にしてください")
            rows.append(
                {
                    "jan": row.get("JAN") or row.get("JANコード") or row.get("jan") or "",
                    "product_name": row.get("商品名") or row.get("product_name") or "",
                    "reason": row.get("理由") or row.get("reason") or "",
                }
            )
    elif suffix in (".pdf", ".png", ".jpg", ".jpeg"):
        value = None
        if suffix == ".pdf":
            try:
                value = extract_inventory(raw)
            except DocumentError:
                pass
        if value is None:
            if consent is not True:
                raise DocumentError("画像・手書きPDFはAI送信への同意が必要です")
            key = ApiCredentials().load()
            if not key:
                raise DocumentError("AI・API設定でキーを保存してください")
            value = AiUsage(paths.state).invoke(
                "exclusion-list", lambda: extract(raw, key, purpose="exclusions")
            )
            method = "ai"
        rows = [
            {**row, "exclude": True, "reason": "担当者確認による対象外"} for row in value["rows"]
        ]
        complete = value["complete"]
    else:
        raise DocumentError("JSON・CSV・PDF・PNG・JPEGを選んでください")
    if not isinstance(rows, list) or not rows or len(rows) > 1000:
        raise DocumentError("商品を取得できませんでした。1000明細以内で確認してください")
    if any(not isinstance(row, dict) for row in rows):
        raise DocumentError("商品明細の形式を確認してください")
    if master:
        flags = [row.get("exclude", True) for row in rows]
        rows = suggest_rows([{**row, "exclude": False} for row in rows], master)
        rows = [{**row, "exclude": flag} for row, flag in zip(rows, flags, strict=True)]
    products = []
    seen = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("exclude", True)) is not bool:
            raise DocumentError("対象外指定の形式を確認してください")
        jan = str(row.get("jan") or "").strip()
        product_name = str(row.get("product_name") or "").strip()[:200]
        if jan and jan in seen:
            if seen[jan] != row.get("exclude", True):
                raise DocumentError("同一JANの対象外・解除が重複しています。原本を確認してください")
            continue
        if jan:
            seen[jan] = row.get("exclude", True)
        products.append(
            {
                "jan": jan,
                "product_name": product_name,
                "exclude": row.get("exclude", True),
                "reason": str(row.get("reason") or "担当者確認による対象外")[:500],
                "issue": "" if valid_jan(jan) else "13桁JANをマスター・原本で確認してください",
            }
        )
    return {
        "products": products,
        "complete": complete,
        "method": method,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_name": name,
    }
