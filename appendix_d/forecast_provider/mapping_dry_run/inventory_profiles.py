"""在庫CSVの列構造を原値なしで一括診断する。"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from ..ingestion.processor import detect_encoding
from .sources import MappingDryRunSourceCatalog

FIELD_CANDIDATES = {
    "date": ("ヘッダ入荷日", "明細入荷日", "登録日"),
    "product_code": ("商品コード",),
    "product_name": ("商品名",),
    "quantity": ("明細資産数量", "内訳資産数量"),
    "center": ("明細倉庫コード", "ヘッダ倉庫コード"),
    "unit": ("明細荷姿単位コード", "内訳荷姿単位コード"),
    "jan": ("JAN", "JANコード"),
}


class InventoryProfileError(ValueError):
    pass


class InventoryStructureProfiler:
    def __init__(self, input_root: Path | None):
        self.input_root = input_root
        self.sources = MappingDryRunSourceCatalog(input_root)

    def profile(self, source_prefix: str) -> dict:
        paths = [
            path
            for path in self.sources.paths_under(source_prefix)
            if "在庫" in path.rsplit("/", 1)[-1]
        ]
        if not paths:
            raise InventoryProfileError("ファイル名に「在庫」を含むCSVがありません")
        headers = Counter(self._header(path) for path in paths)
        field_candidates = {}
        for field, candidates in FIELD_CANDIDATES.items():
            values = []
            for candidate in candidates:
                coverage = sum(count for header, count in headers.items() if candidate in header)
                values.append({"column": candidate, "file_count": coverage})
            field_candidates[field] = values
        patterns = [
            {
                "header_sha256": hashlib.sha256(
                    json.dumps(header, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
                "file_count": count,
                "column_count": len(header),
            }
            for header, count in sorted(headers.items(), key=lambda item: (-item[1], item[0]))
        ]
        return {
            "source_prefix": source_prefix,
            "status": "MAPPING_DECISION_REQUIRED",
            "file_count": len(paths),
            "header_pattern_count": len(headers),
            "patterns": patterns,
            "field_candidates": field_candidates,
            "issues": self._issues(field_candidates, len(paths)),
        }

    def _header(self, source_path: str) -> tuple[str, ...]:
        assert self.input_root is not None
        path = self.input_root.resolve(strict=True) / source_path
        with path.open("rb") as stream:
            data = stream.readline(131_073)
        encoding, error = detect_encoding(data)
        if error or encoding is None:
            raise InventoryProfileError("文字コードを判定できない在庫CSVがあります")
        try:
            return tuple(next(csv.reader([data.decode(encoding)])))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise InventoryProfileError("ヘッダーを解析できない在庫CSVがあります") from exc

    @staticmethod
    def _issues(fields: dict, total: int) -> list[str]:
        issues = []
        if not any(value["file_count"] == total for value in fields["jan"]):
            issues.append("JAN_COLUMN_MISSING")
        for field in ("date", "quantity", "center", "unit"):
            complete = [value for value in fields[field] if value["file_count"] == total]
            if len(complete) > 1:
                issues.append(f"{field.upper()}_COLUMN_AMBIGUOUS")
            elif not complete:
                issues.append(f"{field.upper()}_COLUMN_INCOMPLETE")
        return issues
