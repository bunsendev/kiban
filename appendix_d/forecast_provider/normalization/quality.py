"""正規化済み行と原本台帳から品質集計を作る。"""

from decimal import Decimal


def build_quality(db) -> dict:
    row_statuses = {
        row[0]: row[1]
        for row in db.execute("SELECT status,count(*) FROM shipment_rows GROUP BY status")
    }
    jobs = {
        row[0]: row[1]
        for row in db.execute("SELECT status,count(*) FROM normalization_jobs GROUP BY status")
    }
    source_rows = [
        dict(row)
        for row in db.execute(
            "SELECT center_id,shipment_date,quantity,status,error FROM shipment_rows"
        )
    ]
    file_statuses = {
        row[0]: row[1]
        for row in db.execute("SELECT status,count(*) FROM source_files GROUP BY status")
    }
    encodings = {
        row[0]: row[1]
        for row in db.execute(
            "SELECT encoding,count(*) FROM source_files "
            "WHERE encoding IS NOT NULL GROUP BY encoding"
        )
    }
    center_month = {}
    errors = {}
    for row in source_rows:
        if row["error"]:
            for message in row["error"].split("; "):
                errors[message] = errors.get(message, 0) + 1
        if row["center_id"] and row["shipment_date"]:
            key = (row["center_id"], row["shipment_date"][:7])
            bucket = center_month.setdefault(
                key,
                {"accepted_rows": 0, "quarantined_rows": 0, "accepted_quantity": Decimal(0)},
            )
            bucket[f"{row['status'].lower()}_rows"] += 1
            if row["status"] == "ACCEPTED" and row["quantity"] is not None:
                bucket["accepted_quantity"] += Decimal(row["quantity"])
    monthly = [
        {"center_id": key[0], "month": key[1], **value}
        for key, value in sorted(center_month.items())
    ]
    for item in monthly:
        item["accepted_quantity"] = str(item["accepted_quantity"])
    return {
        "files": file_statuses,
        "encodings": encodings,
        "jobs": jobs,
        "rows": row_statuses,
        "center_month": monthly,
        "errors": errors,
    }
