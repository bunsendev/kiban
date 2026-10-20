"""Evidence-based movement classification and an independent event ledger.

Snapshots remain authoritative: these deltas must not be added to a snapshot
which already includes the same events. No destination receipt is inferred.
"""

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

VERSION = "warehouse-movement-v1"


def shipment_class(row):
    """Only our explicit, evidenced contract is automatically classifiable.

    Legacy document/type codes require a separately confirmed mapping. Names,
    matching quantities and the presence of a destination are not evidence.
    """
    kind = str(row.get("movement_kind") or "").strip()
    if not str(row.get("classification_evidence") or "").strip():
        return "UNRESOLVED"
    if kind == "CUSTOMER_SHIPMENT":
        return kind
    if (
        kind in {"TRANSFER_OUT", "TRANSFER_IN"}
        and all(
            str(row.get(k) or "").strip()
            for k in ("transfer_id", "source_location", "destination_location")
        )
        and row["source_location"] != row["destination_location"]
    ):
        return kind
    return "UNRESOLVED"


def _quantity(value):
    try:
        q = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("数量は有限の非負数で入力してください") from exc
    if not q.is_finite() or q < 0:
        raise ValueError("数量は有限の非負数で入力してください")
    return q


class TransferLedger:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def ingest(self, rows, source_sha, reviewer):
        if not reviewer.strip():
            raise ValueError("分類確認者を入力してください")
        events = []
        for number, original in enumerate(rows, 2):
            row = {str(k): str(v or "").strip() for k, v in original.items()}
            if None in original or any(v is None for v in original.values()):
                raise ValueError(f"{number}行目のCSV列数を確認してください")
            for k in ("event_id", "event_date", "product", "unit", "quantity"):
                if not row.get(k):
                    raise ValueError(f"{number}行目の{k}が必要です")
            date.fromisoformat(row["event_date"])
            row["quantity"] = format(_quantity(row["quantity"]), "f")
            if "." in row["quantity"]:
                row["quantity"] = row["quantity"].rstrip("0").rstrip(".")
            if row["unit"] not in {"CASE", "EACH"}:
                raise ValueError("単位はCASE（ボール）またはEACH（バラ）です")
            row["classification"] = shipment_class(row)
            if row["classification"].startswith("TRANSFER") and not row.get("line_id"):
                raise ValueError("移動の明細ID（line_id）が必要です")
            row.update(
                source_sha256=source_sha, source_row=number, reviewer=reviewer, version=VERSION
            )
            events.append(row)
        with self.connect() as db:
            for row in events:
                body = json.dumps(row, ensure_ascii=False, sort_keys=True)
                existing = db.execute(
                    "SELECT body FROM events WHERE id=?", (row["event_id"],)
                ).fetchone()
                if existing and existing[0] != body:
                    raise ValueError("同一event_idの内容が異なります。元伝票を確認してください")
                db.execute("INSERT OR IGNORE INTO events VALUES (?,?)", (row["event_id"], body))
            # Reject mismatched pairs atomically, including conflicts with prior imports.
            self._groups([json.loads(r[0]) for r in db.execute("SELECT body FROM events")])
        return {"rows": len(events), "source_sha256": source_sha}

    def rows(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM events ORDER BY id")]

    @staticmethod
    def _groups(rows):
        groups = defaultdict(dict)
        for r in rows:
            if not r["classification"].startswith("TRANSFER"):
                continue
            key = (r["transfer_id"], r["line_id"])
            side = r["classification"]
            if side in groups[key]:
                raise ValueError("同一移動明細の同じ側が複数あります。event_idを再利用してください")
            groups[key][side] = r
        for pair in groups.values():
            if len(pair) == 2:
                a, b = pair["TRANSFER_OUT"], pair["TRANSFER_IN"]
                if (
                    any(
                        a.get(k) != b.get(k)
                        for k in (
                            "product",
                            "unit",
                            "quantity",
                            "source_location",
                            "destination_location",
                        )
                    )
                    or b["event_date"] < a["event_date"]
                ):
                    raise ValueError("移動の出庫・入庫明細が一致しません")
        return groups

    def report(self, start, end):
        date.fromisoformat(start)
        date.fromisoformat(end)
        if start > end:
            raise ValueError("期間の開始・終了を確認してください")
        all_rows = self.rows()
        rows = [r for r in all_rows if start <= r["event_date"] <= end]
        groups = self._groups(all_rows)
        aggregates = defaultdict(lambda: {"ids": set(), "quantity": Decimal(0)})
        movements = []
        for (tid, line), pair in sorted(groups.items()):
            out = pair.get("TRANSFER_OUT")
            # Counts and volumes use actual departures only, never both sides.
            if not out or not start <= out["event_date"] <= end:
                continue
            received = pair.get("TRANSFER_IN")
            status = "RECEIVED" if received and received["event_date"] <= end else "IN_TRANSIT"
            movements.append(out | {"receipt_status": status, "line_id": line})
            for dimension, value in (
                ("source", out["source_location"]),
                ("destination", out["destination_location"]),
                ("route", out["source_location"] + " → " + out["destination_location"]),
                ("month", out["event_date"][:7]),
                ("product", out["product"]),
            ):
                key = (dimension, value, out["product"], out["unit"])
                aggregates[key]["ids"].add(
                    (tid, out["source_location"], out["destination_location"])
                )
                aggregates[key]["quantity"] += _quantity(out["quantity"])
        deltas = defaultdict(Decimal)
        for r in rows:
            kind = r["classification"]
            if kind in {"TRANSFER_OUT", "TRANSFER_IN"}:
                loc = r["source_location"] if kind == "TRANSFER_OUT" else r["destination_location"]
                deltas[(r["product"], loc, r["unit"])] += _quantity(r["quantity"]) * (
                    -1 if kind == "TRANSFER_OUT" else 1
                )
        customer = defaultdict(Decimal)
        for r in rows:
            if r["classification"] == "CUSTOMER_SHIPMENT":
                customer[(r["product"], r["unit"])] += _quantity(r["quantity"])
        return {
            "customer_quantities": [
                {"product": k[0], "unit": k[1], "quantity": str(q)}
                for k, q in sorted(customer.items())
            ],
            "version": VERSION,
            "start": start,
            "end": end,
            "transfer_count": len(
                {
                    (r["transfer_id"], r["source_location"], r["destination_location"])
                    for r in movements
                }
            ),
            "aggregates": [
                {
                    "dimension": k[0],
                    "value": k[1],
                    "product": k[2],
                    "unit": k[3],
                    "count": len(v["ids"]),
                    "quantity": str(v["quantity"]),
                }
                for k, v in sorted(aggregates.items())
            ],
            "inventory_deltas": [
                {"product": k[0], "location": k[1], "unit": k[2], "delta": str(q)}
                for k, q in sorted(deltas.items())
            ],
            "unpaired_receipt_rows": sum(
                r["classification"] == "TRANSFER_IN"
                and "TRANSFER_OUT" not in groups[(r["transfer_id"], r["line_id"])]
                for r in rows
                if r["classification"] == "TRANSFER_IN"
            ),
            "unresolved_count": sum(r["classification"] == "UNRESOLVED" for r in rows),
            "customer_shipment_rows": sum(r["classification"] == "CUSTOMER_SHIPMENT" for r in rows),
            "observed_products": len({r["product"] for r in rows}),
            "observed_dates": len({r["event_date"] for r in rows}),
            "movements": movements,
            "events": rows,
            "inventory_application": "EVENT_DELTAS_ONLY_NOT_APPLIED_TO_EXISTING_SNAPSHOTS",
        }


def compare(before, after, *, coverage_confirmed=False):
    """Actual reduction needs explicit period-completeness confirmation."""
    coverage_confirmed = coverage_confirmed and not (
        before["unresolved_count"]
        or after["unresolved_count"]
        or before["unpaired_receipt_rows"]
        or after["unpaired_receipt_rows"]
    )

    def rate(a, b):
        return None if not coverage_confirmed or not a else str((a - b) / a * 100)

    def amounts(report):
        return {
            (r["product"], r["unit"]): Decimal(r["quantity"])
            for r in report["aggregates"]
            if r["dimension"] == "product"
        }

    a, b = amounts(before), amounts(after)
    return {
        "coverage_confirmed": coverage_confirmed,
        "causal_effect_proven": False,
        "count_reduction_percent": rate(
            Decimal(before["transfer_count"]), Decimal(after["transfer_count"])
        ),
        "quantities": [
            {
                "product": k[0],
                "unit": k[1],
                "before": str(a.get(k, 0)),
                "after": str(b.get(k, 0)),
                "reduction_percent": rate(a.get(k, Decimal(0)), b.get(k, Decimal(0))),
            }
            for k in sorted(a.keys() | b.keys())
        ],
        "before": before,
        "after": after,
    }


def source_digest(raw):
    return hashlib.sha256(raw).hexdigest()
