"""在庫CSV全行を商品・倉庫・日付別の日次残高へ集約するWorker処理。"""

import csv
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..ingestion.processor import detect_encoding
from ..mapping_dry_run.inventory_normalization_preview import FILENAME_DATE
from ..mapping_dry_run.sources import MappingDryRunSourceCatalog

REQUIRED_COLUMNS = {"商品コード", "明細バラ数", "明細倉庫コード"}


class InventoryNormalizationProcessor:
    def __init__(self, store, input_root: Path):
        self.store = store
        self.input_root = input_root

    def process_next(self):
        job = self.store.claim()
        if job is None:
            return False
        try:
            mapping = self._mapping(job["product_mapping_id"])
            paths = [
                p
                for p in MappingDryRunSourceCatalog(self.input_root).paths_under(
                    job["source_prefix"]
                )
                if "在庫" in Path(p).name
            ]
            if not paths:
                raise ValueError("在庫CSVがありません")
            totals = defaultdict(Decimal)
            source_quantity = Decimal(0)
            reasons = Counter()
            accepted = quarantined = 0
            for index, source_path in enumerate(paths, 1):
                date = self._date(source_path)
                for row in self._rows(source_path):
                    code = (row.get("商品コード") or "").strip()
                    center = (row.get("明細倉庫コード") or "").strip()
                    try:
                        quantity = Decimal((row.get("明細バラ数") or "").replace(",", ""))
                        valid_quantity = quantity.is_finite() and quantity >= 0
                    except InvalidOperation:
                        valid_quantity = False
                    row_reasons = []
                    if date is None:
                        row_reasons.append("INVENTORY_DATE_INVALID")
                    if code not in mapping:
                        row_reasons.append("PRODUCT_MAPPING_MISSING")
                    if not center:
                        row_reasons.append("CENTER_MISSING")
                    if not valid_quantity:
                        row_reasons.append("QUANTITY_INVALID")
                    if row_reasons:
                        quarantined += 1
                        reasons.update(row_reasons)
                    else:
                        accepted += 1
                        source_quantity += quantity
                        totals[(date, mapping[code], center, job["unit_value"])] += quantity
                self.store.progress(
                    job["job_id"], len(paths), index, accepted, quarantined, reasons
                )
            values = [
                (str(date), jan, center, unit, str(quantity))
                for (date, jan, center, unit), quantity in sorted(totals.items())
            ]
            self.store.complete(
                job["job_id"],
                values,
                str(source_quantity),
                str(sum(totals.values(), Decimal(0))),
            )
        except Exception:
            self.store.fail(job["job_id"], "INVENTORY_NORMALIZATION_FAILED")
        return True

    def _mapping(self, mapping_id):
        path = self.input_root / "product-jan-mappings" / f"{mapping_id}.csv"
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return {
                (row["商品コード"]).strip(): (row["JAN"]).strip() for row in csv.DictReader(stream)
            }

    @staticmethod
    def _date(source_path):
        match = FILENAME_DATE.search(Path(source_path).name)
        if match is None:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            return None

    def _rows(self, source_path):
        path = self.input_root / source_path
        with path.open("rb") as stream:
            encoding, error = detect_encoding(stream.read(131_072))
        if error or encoding is None:
            raise ValueError("在庫CSVの文字コードを判定できません")
        with path.open(encoding=encoding, newline="") as stream:
            reader = csv.DictReader(stream)
            if not REQUIRED_COLUMNS.issubset(reader.fieldnames or []):
                raise ValueError("在庫CSVの必須列がありません")
            yield from reader
