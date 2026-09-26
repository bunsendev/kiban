"""在庫mapping候補の値充足と整合性を原値なしで集計する。"""

from __future__ import annotations

import csv
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..ingestion.processor import detect_stream_encoding

FILENAME_DATE = re.compile(r"_(\d{8})\.csv$", re.IGNORECASE)
SAMPLE_ROWS_PER_FILE = 100


class InventoryMappingAnalyzer:
    def __init__(self, input_root: Path):
        self.input_root = input_root.resolve(strict=True)

    def analyze(self, source_paths: list[str]) -> dict:
        counters = {
            "sampled_rows": 0,
            "quantity_present": 0,
            "quantity_numeric": 0,
            "quantity_nonnegative": 0,
            "product_code_present": 0,
            "product_name_present": 0,
            "detail_center_present": 0,
            "center_pair_equal": 0,
        }
        filename_dates = 0
        for source_path in source_paths:
            filename_dates += bool(FILENAME_DATE.search(Path(source_path).name))
            self._sample_file(source_path, counters)
        rows = counters["sampled_rows"]
        date_complete = filename_dates == len(source_paths)
        quantity_complete = rows > 0 and counters["quantity_nonnegative"] == rows
        centers_equal = rows > 0 and counters["center_pair_equal"] == rows
        return {
            "sample_rows_per_file": SAMPLE_ROWS_PER_FILE,
            "sampled_rows": rows,
            "filename_date_file_count": filename_dates,
            "quality_counts": counters,
            "recommendation": {
                "date_source": "FILENAME_YYYYMMDD" if date_complete else None,
                "product_code_column": "商品コード",
                "product_name_column": "商品名",
                "quantity_column": "明細バラ数" if quantity_complete else None,
                "center_column": "明細倉庫コード" if centers_equal else None,
                "unit_value": None,
                "jan_mapping_required": True,
                "status": (
                    "UNIT_AND_PRODUCT_MASTER_REQUIRED"
                    if date_complete and quantity_complete and centers_equal
                    else "SOURCE_REVIEW_REQUIRED"
                ),
            },
        }

    def _sample_file(self, source_path: str, counters: dict[str, int]) -> None:
        path = self.input_root / source_path
        with path.open("rb") as stream:
            encoding, error = detect_stream_encoding(stream)
        if error or encoding is None:
            return
        with path.open(encoding=encoding, newline="") as stream:
            for index, row in enumerate(csv.DictReader(stream)):
                if index >= SAMPLE_ROWS_PER_FILE:
                    break
                counters["sampled_rows"] += 1
                self._count_row(row, counters)

    @staticmethod
    def _count_row(row: dict[str, str], counters: dict[str, int]) -> None:
        quantity = (row.get("明細バラ数") or "").strip()
        if quantity:
            counters["quantity_present"] += 1
            try:
                value = Decimal(quantity.replace(",", ""))
            except InvalidOperation:
                pass
            else:
                counters["quantity_numeric"] += 1
                counters["quantity_nonnegative"] += value >= 0
        for column, counter in (
            ("商品コード", "product_code_present"),
            ("商品名", "product_name_present"),
            ("明細倉庫コード", "detail_center_present"),
        ):
            counters[counter] += bool((row.get(column) or "").strip())
        header_center = (row.get("ヘッダ倉庫コード") or "").strip()
        detail_center = (row.get("明細倉庫コード") or "").strip()
        counters["center_pair_equal"] += bool(header_center and header_center == detail_center)
