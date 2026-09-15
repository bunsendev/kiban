"""在庫商品コードとJANの接続可否を診断し、対応表templateを作る。"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import uuid
from pathlib import Path

from ..ingestion.processor import detect_encoding
from .sources import MappingDryRunSourceCatalog

SAMPLE_ROWS_PER_FILE = 100
MAX_MAPPING_BYTES = 5 * 1024 * 1024
MAX_MAPPING_ROWS = 10_000
MAPPING_HEADER = ["商品コード", "商品名", "JAN", "確認メモ"]


class ProductBridgeService:
    def __init__(self, input_root: Path | None):
        self.input_root = input_root
        self.sources = MappingDryRunSourceCatalog(input_root)

    def analyze(self, source_prefix: str) -> dict:
        shipments, inventories = self._paths(source_prefix)
        shipment_rows = shipment_pairs = 0
        inventory_rows = 0
        inventory_codes = set()
        for path in shipments:
            for row in self._sample(path):
                shipment_rows += 1
                shipment_pairs += bool(
                    (row.get("商品コード") or "").strip() and (row.get("JAN") or "").strip()
                )
        for path in inventories:
            for row in self._sample(path):
                inventory_rows += 1
                code = (row.get("商品コード") or "").strip()
                if code:
                    inventory_codes.add(code)
        return {
            "shipment_file_count": len(shipments),
            "inventory_file_count": len(inventories),
            "shipment_sampled_rows": shipment_rows,
            "shipment_code_jan_pair_rows": shipment_pairs,
            "inventory_sampled_rows": inventory_rows,
            "inventory_distinct_product_codes": len(inventory_codes),
            "status": "EXTERNAL_MAPPING_REQUIRED" if not shipment_pairs else "REVIEW_REQUIRED",
        }

    def template(self, source_prefix: str) -> str:
        products = self._inventory_products(source_prefix)
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(MAPPING_HEADER)
        for code, name in sorted(products.items()):
            writer.writerow([code, name, "", ""])
        return "\ufeff" + output.getvalue()

    def import_mapping(self, source_prefix: str, content: bytes) -> dict:
        if not content or len(content) > MAX_MAPPING_BYTES:
            raise ValueError("JAN対応表は1 byte以上5 MiB以下にしてください")
        products = self._inventory_products(source_prefix)
        try:
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            if reader.fieldnames != MAPPING_HEADER:
                raise ValueError("JAN対応表の列がtemplateと一致しません")
            rows = list(reader)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValueError("JAN対応表はUTF-8 CSVで保存してください") from exc
        if not rows or len(rows) > MAX_MAPPING_ROWS:
            raise ValueError("JAN対応表の行数が不正です")
        seen = set()
        duplicates = invalid_jans = unknown_codes = completed = 0
        normalized = []
        for row in rows:
            code = (row.get("商品コード") or "").strip()
            jan = (row.get("JAN") or "").strip()
            if code in seen:
                duplicates += 1
            seen.add(code)
            unknown_codes += code not in products
            if jan:
                if self._valid_jan(jan):
                    completed += code in products
                else:
                    invalid_jans += 1
            normalized.append(
                [code, products.get(code, ""), jan, (row.get("確認メモ") or "").strip()]
            )
        missing_codes = len(set(products) - seen)
        issues = {
            "duplicate_product_codes": duplicates,
            "invalid_jans": invalid_jans,
            "unknown_product_codes": unknown_codes,
            "missing_product_codes": missing_codes,
            "blank_jans": len(products) - completed,
        }
        ready = all(value == 0 for value in issues.values()) and len(rows) == len(products)
        mapping_id = self._save(normalized) if ready else None
        return {
            "status": "READY" if ready else "CORRECTION_REQUIRED",
            "mapping_id": mapping_id,
            "expected_product_count": len(products),
            "completed_product_count": completed,
            "issues": issues,
        }

    def _inventory_products(self, source_prefix: str) -> dict[str, str]:
        _, inventories = self._paths(source_prefix)
        products = {}
        for path in inventories:
            for row in self._sample(path):
                code = (row.get("商品コード") or "").strip()
                name = (row.get("商品名") or "").strip()
                if code:
                    products.setdefault(code, name)
        return products

    def _save(self, rows: list[list[str]]) -> str:
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(MAPPING_HEADER)
        writer.writerows(sorted(rows))
        content = ("\ufeff" + output.getvalue()).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        mapping_id = f"product-jan-{digest}"
        assert self.input_root is not None
        directory = self.input_root.resolve(strict=True) / "product-jan-mappings"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{mapping_id}.csv"
        if not destination.exists():
            pending = directory / f".{uuid.uuid4().hex}.pending"
            try:
                pending.write_bytes(content)
                os.replace(pending, destination)
            finally:
                pending.unlink(missing_ok=True)
        return mapping_id

    @staticmethod
    def _valid_jan(value: str) -> bool:
        if not value.isdigit() or len(value) not in {8, 13}:
            return False
        digits = [int(character) for character in value]
        body = digits[:-1]
        total = sum(
            digit * (3 if (len(body) - index) % 2 else 1) for index, digit in enumerate(body)
        )
        return (10 - total % 10) % 10 == digits[-1]

    def _paths(self, source_prefix: str) -> tuple[list[str], list[str]]:
        paths = self.sources.paths_under(source_prefix)
        shipments = [path for path in paths if "出荷" in Path(path).name]
        inventories = [path for path in paths if "在庫" in Path(path).name]
        if not inventories:
            raise ValueError("在庫CSVがありません")
        return shipments, inventories

    def _sample(self, source_path: str):
        assert self.input_root is not None
        path = self.input_root.resolve(strict=True) / source_path
        with path.open("rb") as stream:
            encoding, error = detect_encoding(stream.read(131_072))
        if error or encoding is None:
            return
        with path.open(encoding=encoding, newline="") as stream:
            for index, row in enumerate(csv.DictReader(stream)):
                if index >= SAMPLE_ROWS_PER_FILE:
                    break
                yield row
