"""Local, review-required product suggestions; never quantity or date inference."""

import re

from .document_evidence import valid_jan
from .document_master import normalized


def suggest_rows(rows, master, approved_rows=()):
    products = master["products"]
    output = []
    for original in rows:
        row = dict(original)
        if row.get("exclude") or valid_jan(row.get("jan", "")):
            output.append(row)
            continue
        name = normalized(row.get("product_name", ""))
        matches = [p for p in products if name and normalized(p["product_name"]) == name]
        raw_jan = str(row.get("jan") or row.get("source_jan") or "")
        suffix = raw_jan[-6:] if re.fullmatch(r"[0-9]{6,13}", raw_jan) else ""
        suffix_matches = [p for p in products if suffix and p["jan"].endswith(suffix)]
        if suffix_matches:
            if matches:
                matches = [p for p in matches if p in suffix_matches]
            else:
                matches = suffix_matches
        for prior in approved_rows:
            if (
                not prior.get("exclude")
                and prior.get("master_version") == master["version"]
                and name
                and normalized(prior.get("product_name", "")) == name
            ):
                matches.extend(
                    p
                    for p in products
                    if p["jan"] == prior.get("jan")
                    and p["product_code"] == prior.get("product_code")
                )
        unique = {(p["jan"], p["product_code"]): p for p in matches}
        if len(unique) == 1:
            product = next(iter(unique.values()))
            row.update(
                source_jan=row.get("source_jan") or row.get("jan", ""),
                jan=product["jan"],
                product_code=product["product_code"],
                master_version=master["version"],
                master_cell=product["cell"],
            )
            row["note"] = (
                str(row.get("note") or "") + " 商品候補をローカル照合で入力。原本確認が必要。"
            )
        elif len(unique) > 1:
            row["note"] = (
                str(row.get("note") or "") + " 商品候補が複数あります。個別に確認してください。"
            )
        output.append(row)
    return output
