"""在庫CSVを台帳更新なしで正規化候補へ変換する事前検査。"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..ingestion.processor import detect_stream_encoding
from .sources import MappingDryRunSourceCatalog

FILENAME_DATE = re.compile(r"_(\d{8})\.csv$", re.IGNORECASE)


class InventoryNormalizationPreview:
    def __init__(self, input_root: Path | None):
        self.input_root = input_root
        self.sources = MappingDryRunSourceCatalog(input_root)

    def run(
        self, source_prefix: str, product_mapping_id: str, unit_value: str, sample_rows: int
    ) -> dict:
        if self.input_root is None:
            raise ValueError("入力rootが設定されていません")
        mapping = self._load_mapping(product_mapping_id)
        paths = [
            path for path in self.sources.paths_under(source_prefix) if "在庫" in Path(path).name
        ]
        if not paths:
            raise ValueError("在庫CSVがありません")
        reasons = Counter()
        accepted = sampled = 0
        for source_path in paths:
            file_date = self._filename_date(source_path)
            for row in self._sample(source_path, sample_rows):
                sampled += 1
                row_reasons = self._row_reasons(row, file_date, mapping)
                if row_reasons:
                    reasons.update(row_reasons)
                else:
                    accepted += 1
        summary = {
            "source_prefix": source_prefix,
            "product_mapping_id": product_mapping_id,
            "unit_value": unit_value,
            "file_count": len(paths),
            "sample_rows_per_file": sample_rows,
            "sampled_rows": sampled,
            "accepted_rows": accepted,
            "quarantined_rows": sampled - accepted,
            "reason_counts": dict(sorted(reasons.items())),
            "outcome": "READY_FOR_INVENTORY_NORMALIZATION"
            if sampled and accepted == sampled
            else "REVIEW_REQUIRED",
        }
        evidence = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {
            **summary,
            "report_id": f"inventory-preview-{hashlib.sha256(evidence.encode()).hexdigest()}",
        }

    def _load_mapping(self, mapping_id: str) -> dict[str, str]:
        assert self.input_root is not None
        path = self.input_root.resolve(strict=True) / "product-jan-mappings" / f"{mapping_id}.csv"
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
        except OSError as exc:
            raise ValueError("JAN対応表が見つかりません") from exc
        return {
            (row.get("商品コード") or "").strip(): (row.get("JAN") or "").strip() for row in rows
        }

    @staticmethod
    def _filename_date(source_path: str):
        match = FILENAME_DATE.search(Path(source_path).name)
        if match is None:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            return None

    @staticmethod
    def _row_reasons(row: dict[str, str], file_date, mapping: dict[str, str]) -> set[str]:
        reasons = set()
        code = (row.get("商品コード") or "").strip()
        quantity = (row.get("明細バラ数") or "").strip()
        center = (row.get("明細倉庫コード") or "").strip()
        if file_date is None:
            reasons.add("INVENTORY_DATE_INVALID")
        if not code or code not in mapping:
            reasons.add("PRODUCT_MAPPING_MISSING")
        if not center:
            reasons.add("CENTER_MISSING")
        try:
            value = Decimal(quantity.replace(",", ""))
            if not value.is_finite() or value < 0:
                raise InvalidOperation
        except InvalidOperation:
            reasons.add("QUANTITY_INVALID")
        return reasons

    def _sample(self, source_path: str, limit: int):
        assert self.input_root is not None
        path = self.input_root.resolve(strict=True) / source_path
        with path.open("rb") as stream:
            encoding, error = detect_stream_encoding(stream)
        if error or encoding is None:
            return
        with path.open(encoding=encoding, newline="") as stream:
            for index, row in enumerate(csv.DictReader(stream)):
                if index >= limit:
                    break
                yield row
