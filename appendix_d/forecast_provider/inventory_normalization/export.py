"""時点安全な在庫特徴ビューを決定的CSVへ変換する。"""

import csv
import hashlib
import io


def feature_view_csv(view: dict) -> tuple[bytes, str]:
    if view["status"] != "READY":
        raise ValueError("READYの在庫特徴ビューだけを出力できます")
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(
        [
            "feature_view_id",
            "canonical_product_id",
            "center_id",
            "ds",
            "unit",
            "inventory_quantity",
            "available_at",
        ]
    )
    for item in view["items"]:
        writer.writerow(
            [
                view["view_id"],
                item["canonical_product_id"],
                item["center_id"],
                item["ds"],
                item["unit"],
                item["inventory_quantity"],
                item["available_at"],
            ]
        )
    content = ("\ufeff" + output.getvalue()).encode("utf-8")
    return content, hashlib.sha256(content).hexdigest()
