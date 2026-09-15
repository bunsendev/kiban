"""在庫商品コードとJANの接続可否を診断し、対応表templateを作る。"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from ..ingestion.processor import detect_encoding
from .sources import MappingDryRunSourceCatalog

SAMPLE_ROWS_PER_FILE = 100


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
        _, inventories = self._paths(source_prefix)
        products = {}
        for path in inventories:
            for row in self._sample(path):
                code = (row.get("商品コード") or "").strip()
                name = (row.get("商品名") or "").strip()
                if code:
                    products.setdefault(code, name)
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(["商品コード", "商品名", "JAN", "確認メモ"])
        for code, name in sorted(products.items()):
            writer.writerow([code, name, "", ""])
        return "\ufeff" + output.getvalue()

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
