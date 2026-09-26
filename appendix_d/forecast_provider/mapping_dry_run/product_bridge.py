"""在庫商品コードとJANの接続可否を診断し、対応表templateを作る。"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import uuid
from collections import defaultdict
from pathlib import Path

from ..ingestion.processor import detect_stream_encoding
from .product_jan_candidates import (
    ProductJanCandidate,
    ProductJanCandidateStatus,
    build_product_jan_candidates,
)
from .sources import MappingDryRunSourceCatalog

SAMPLE_ROWS_PER_FILE = 100
MAX_MAPPING_BYTES = 5 * 1024 * 1024
MAX_MAPPING_ROWS = 10_000
MAPPING_HEADER = ["商品コード", "商品名", "JAN", "確認メモ"]
CONFIRMED_NOTE = "確認済み"
UNIQUE_REVIEW_NOTE = "候補（商品名完全一致・要確認）"
DIRECT_REVIEW_NOTE = "候補（出荷商品コード一致・要確認）"
AMBIGUOUS_REVIEW_NOTE = "複数候補（要確認）"
MISSING_REVIEW_NOTE = "候補なし"


class ProductBridgeService:
    def __init__(self, input_root: Path | None):
        self.input_root = input_root
        self.sources = MappingDryRunSourceCatalog(input_root)

    def analyze(self, source_prefix: str) -> dict:
        shipments, inventories = self._paths(source_prefix)
        candidates = self._candidates(shipments, inventories)
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
        counts = {
            status: sum(candidate.status is status for candidate in candidates)
            for status in ProductJanCandidateStatus
        }
        return {
            "shipment_file_count": len(shipments),
            "inventory_file_count": len(inventories),
            "shipment_sampled_rows": shipment_rows,
            "shipment_code_jan_pair_rows": shipment_pairs,
            "inventory_sampled_rows": inventory_rows,
            "inventory_sampled_distinct_product_codes": len(inventory_codes),
            "inventory_distinct_product_codes": len(candidates),
            "candidate_unique_products": counts[ProductJanCandidateStatus.UNIQUE],
            "candidate_ambiguous_products": counts[ProductJanCandidateStatus.AMBIGUOUS],
            "candidate_missing_products": counts[ProductJanCandidateStatus.MISSING],
            "status": (
                "CANDIDATE_REVIEW_REQUIRED"
                if counts[ProductJanCandidateStatus.UNIQUE]
                else "EXTERNAL_MAPPING_REQUIRED"
            ),
        }

    def template(self, source_prefix: str) -> str:
        shipments, inventories = self._paths(source_prefix)
        candidates = self._candidates(shipments, inventories)
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(MAPPING_HEADER)
        for candidate in candidates:
            jan, note = self._template_value(candidate)
            writer.writerow(
                [candidate.product_code, candidate.display_name, jan, note]
            )
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
        completed_codes = set()
        confirmed_codes = set()
        duplicates = invalid_jans = unknown_codes = unconfirmed_jans = 0
        normalized = []
        for row in rows:
            code = (row.get("商品コード") or "").strip()
            jan = (row.get("JAN") or "").strip()
            note = (row.get("確認メモ") or "").strip()
            if code in seen:
                duplicates += 1
            seen.add(code)
            unknown_codes += code not in products
            if jan:
                if self._valid_jan(jan):
                    if code in products:
                        completed_codes.add(code)
                        if note == CONFIRMED_NOTE:
                            confirmed_codes.add(code)
                        else:
                            unconfirmed_jans += 1
                else:
                    invalid_jans += 1
            normalized.append([code, products.get(code, ""), jan, note])
        missing_codes = len(set(products) - seen)
        issues = {
            "duplicate_product_codes": duplicates,
            "invalid_jans": invalid_jans,
            "unknown_product_codes": unknown_codes,
            "missing_product_codes": missing_codes,
            "blank_jans": len(products) - len(completed_codes),
            "unconfirmed_jans": unconfirmed_jans,
        }
        ready = (
            all(value == 0 for value in issues.values())
            and len(rows) == len(products)
            and len(confirmed_codes) == len(products)
        )
        mapping_id = self._save(normalized) if ready else None
        return {
            "status": "READY" if ready else "CORRECTION_REQUIRED",
            "mapping_id": mapping_id,
            "expected_product_count": len(products),
            "completed_product_count": len(completed_codes),
            "confirmed_product_count": len(confirmed_codes),
            "issues": issues,
        }

    def _inventory_products(self, source_prefix: str) -> dict[str, str]:
        _, inventories = self._paths(source_prefix)
        return {
            code: min(names) if names else ""
            for code, names in self._inventory_names(inventories).items()
        }

    def _inventory_names(self, inventories: list[str]) -> dict[str, set[str]]:
        products: dict[str, set[str]] = defaultdict(set)
        for path in inventories:
            for row in self._rows(path):
                code = (row.get("商品コード") or "").strip()
                name = (row.get("商品名") or "").strip()
                if code:
                    if name:
                        products[code].add(name)
                    else:
                        products.setdefault(code, set())
        return products

    def _candidates(
        self, shipments: list[str], inventories: list[str]
    ) -> tuple[ProductJanCandidate, ...]:
        inventory_names = self._inventory_names(inventories)
        needed_names = {
            name for names in inventory_names.values() for name in names
        }
        shipment_jans: dict[str, set[str]] = defaultdict(set)
        shipment_code_jans: dict[str, set[str]] = defaultdict(set)
        for path in shipments:
            for row in self._rows(path):
                name = (row.get("商品名") or "").strip()
                code = (row.get("商品コード") or "").strip()
                jan = (row.get("JAN") or "").strip()
                if not self._valid_jan(jan):
                    continue
                if name in needed_names:
                    shipment_jans[name].add(jan)
                if code in inventory_names:
                    shipment_code_jans[code].add(jan)
        return build_product_jan_candidates(
            inventory_names, shipment_jans, shipment_code_jans
        )

    @staticmethod
    def _template_value(candidate: ProductJanCandidate) -> tuple[str, str]:
        if candidate.status is ProductJanCandidateStatus.UNIQUE:
            note = (
                DIRECT_REVIEW_NOTE
                if candidate.unique_candidate_is_direct
                else UNIQUE_REVIEW_NOTE
            )
            return candidate.candidate_jans[0], note
        if candidate.status is ProductJanCandidateStatus.AMBIGUOUS:
            values = " / ".join(candidate.candidate_jans)
            return "", f"{AMBIGUOUS_REVIEW_NOTE}: {values}"
        return "", MISSING_REVIEW_NOTE

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
        for index, row in enumerate(self._rows(source_path)):
            if index >= SAMPLE_ROWS_PER_FILE:
                break
            yield row

    def _rows(self, source_path: str):
        assert self.input_root is not None
        path = self.input_root.resolve(strict=True) / source_path
        with path.open("rb") as stream:
            encoding, error = detect_stream_encoding(stream)
        if error or encoding is None:
            raise ValueError("文字コードを判定できないCSVがあります")
        with path.open(encoding=encoding, newline="") as stream:
            yield from csv.DictReader(stream)
