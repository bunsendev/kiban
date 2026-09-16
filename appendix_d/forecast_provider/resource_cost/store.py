"""SQLite/PostgreSQLで共用する資源・費用台帳操作。"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from .contracts import ResourceMeasurement, ResourceMetric, ResourceUsage, UnitPrice
from .domain import make_measurement


class SqliteResourceCostStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    def record_attempt(
        self,
        run_id,
        origin_date,
        attempt,
        usages: tuple[ResourceUsage, ...],
    ) -> list[ResourceMeasurement]:
        values_by_id = {}
        for usage in usages:
            value = make_measurement(run_id, origin_date, attempt, usage)
            previous = values_by_id.get(value.measurement_id)
            if previous is not None and not _same_measurement(previous, value):
                raise ValueError("同じ試行の資源計測sourceが重複しています")
            values_by_id[value.measurement_id] = value
        values = list(values_by_id.values())
        saved = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for value in values:
                db.execute(
                    "INSERT INTO resource_measurements VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT DO NOTHING",
                    (
                        value.measurement_id,
                        value.run_id,
                        value.origin_date.isoformat(),
                        value.attempt,
                        value.metric.value,
                        value.unit,
                        str(value.quantity),
                        value.source,
                        value.identity,
                        value.measured_at.isoformat(),
                    ),
                )
                row = db.execute(
                    "SELECT * FROM resource_measurements WHERE measurement_id=?",
                    (value.measurement_id,),
                ).fetchone()
                current = None if row is None else _measurement(row)
                if current is None or not _same_measurement(current, value):
                    raise ValueError("同じ資源計測IDの内容は変更できません")
                saved.append(current)
        return saved

    def put_unit_price(self, value: UnitPrice) -> UnitPrice:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO resource_unit_prices VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT DO NOTHING",
                (
                    value.price_id,
                    value.provider_id,
                    value.metric.value,
                    value.unit,
                    str(value.unit_price),
                    value.currency,
                    value.retrieved_on.isoformat(),
                    value.source_ref,
                    value.created_by,
                    value.created_at.isoformat(),
                ),
            )
            row = db.execute(
                "SELECT * FROM resource_unit_prices WHERE price_id=?", (value.price_id,)
            ).fetchone()
            current = None if row is None else _price(row)
            if current is None or replace(current, created_at=value.created_at) != value:
                raise ValueError("同じ単価IDの内容は変更できません")
        return current

    def list_unit_prices(
        self, provider_id: str | None = None, metric: ResourceMetric | None = None
    ) -> list[UnitPrice]:
        clauses, params = [], []
        if provider_id is not None:
            clauses.append("provider_id=?")
            params.append(provider_id)
        if metric is not None:
            clauses.append("metric=?")
            params.append(metric.value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM resource_unit_prices"
                f"{where} ORDER BY retrieved_on DESC,created_at DESC,price_id",
                params,
            )
            return [_price(row) for row in rows]

    def summarize(self, run_id: str, *, include_attempts: bool = False) -> dict | None:
        with self._connect() as db:
            run = db.execute(
                "SELECT provider_id FROM forecast_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                return None
            rows = list(
                db.execute(
                    "SELECT * FROM resource_measurements "
                    "WHERE run_id=? ORDER BY metric,measurement_id",
                    (run_id,),
                )
            )
        quantities = {metric: Decimal(0) for metric in ResourceMetric}
        present: set[ResourceMetric] = set()
        for row in rows:
            metric = ResourceMetric(row["metric"])
            quantity = Decimal(str(row["quantity"]))
            if metric == ResourceMetric.PEAK_MEMORY_BYTES:
                quantities[metric] = max(quantities[metric], quantity)
            else:
                quantities[metric] += quantity
            present.add(metric)
        prices = self._latest_prices(run["provider_id"])
        items, currencies, complete, total = [], set(), bool(present), Decimal(0)
        for metric in ResourceMetric:
            quantity = quantities[metric] if metric in present else None
            price = prices.get(metric)
            cost = None if quantity is None or price is None else quantity * price.unit_price
            if quantity is not None and price is None:
                complete = False
            if cost is not None:
                total += cost
                currencies.add(price.currency)
            items.append(
                {
                    "metric": metric.value,
                    "unit": metric.unit,
                    "quantity": None if quantity is None else str(quantity),
                    "unit_price": None if price is None else str(price.unit_price),
                    "currency": None if price is None else price.currency,
                    "price_id": None if price is None else price.price_id,
                    "price_retrieved_on": (
                        None if price is None else price.retrieved_on.isoformat()
                    ),
                    "cost_amount": None if cost is None else str(cost),
                }
            )
        if len(currencies) > 1:
            complete = False
        currency = next(iter(currencies)) if len(currencies) == 1 else None
        result = {
            "run_id": run_id,
            "provider_id": run["provider_id"],
            "measurements": items,
            "pricing_complete": complete,
            "total_cost_amount": str(total) if complete else None,
            "currency": currency if complete else None,
        }
        if include_attempts:
            result["attempt_measurements"] = [
                {
                    "measurement_id": row["measurement_id"],
                    "origin_date": str(row["origin_date"]),
                    "attempt": int(row["attempt"]),
                    "metric": row["metric"],
                    "unit": row["unit"],
                    "quantity": str(row["quantity"]),
                    "source": row["source"],
                    "measured_at": str(row["measured_at"]),
                }
                for row in rows
            ]
        return result

    def _latest_prices(self, provider_id: str) -> dict[ResourceMetric, UnitPrice]:
        values = self.list_unit_prices()
        result = {}
        for metric in ResourceMetric:
            exact = next(
                (
                    item
                    for item in values
                    if item.metric == metric and item.provider_id == provider_id
                ),
                None,
            )
            fallback = next(
                (item for item in values if item.metric == metric and item.provider_id == "*"),
                None,
            )
            if exact or fallback:
                result[metric] = exact or fallback
        return result


def _measurement(row) -> ResourceMeasurement:
    from datetime import date, datetime

    return ResourceMeasurement(
        row["measurement_id"],
        row["run_id"],
        date.fromisoformat(str(row["origin_date"])),
        int(row["attempt"]),
        ResourceMetric(row["metric"]),
        row["unit"],
        Decimal(str(row["quantity"])),
        row["source"],
        row["identity"],
        datetime.fromisoformat(str(row["measured_at"])),
    )


def _same_measurement(current: ResourceMeasurement, expected: ResourceMeasurement) -> bool:
    if expected.identity is None:
        return replace(current, measured_at=expected.measured_at) == expected
    return (
        current.measurement_id,
        current.run_id,
        current.metric,
        current.unit,
        current.quantity,
        current.source,
        current.identity,
    ) == (
        expected.measurement_id,
        expected.run_id,
        expected.metric,
        expected.unit,
        expected.quantity,
        expected.source,
        expected.identity,
    )


def _price(row) -> UnitPrice:
    from datetime import date, datetime

    return UnitPrice(
        row["price_id"],
        row["provider_id"],
        ResourceMetric(row["metric"]),
        row["unit"],
        Decimal(str(row["unit_price"])),
        row["currency"],
        date.fromisoformat(str(row["retrieved_on"])),
        row["source_ref"],
        row["created_by"],
        datetime.fromisoformat(str(row["created_at"])),
    )
