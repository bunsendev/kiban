"""内容アドレス方式のmappingドライラン証跡を列挙する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .evidence import sanitize_report
from .evidence_schema import HEX_SHA256, InvalidReportError, unique_object


class MappingDryRunCatalog:
    def __init__(self, output_root: Path | None, max_report_bytes: int = 262_144) -> None:
        self.output_root = output_root
        self.max_report_bytes = max_report_bytes

    @property
    def configured(self) -> bool:
        return self.output_root is not None

    def _directory(self) -> Path | None:
        if self.output_root is None:
            return None
        directory = self.output_root / "mapping-dry-run"
        if directory.is_symlink() or not directory.is_dir():
            return None
        return directory

    def _read(self, path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file() or not HEX_SHA256.fullmatch(path.stem):
            raise InvalidReportError("証跡fileが不正です")
        if path.suffix != ".json":
            raise InvalidReportError("証跡拡張子が不正です")
        try:
            with path.open("rb") as stream:
                content = stream.read(self.max_report_bytes + 1)
        except OSError as exc:
            raise InvalidReportError("証跡を読込めません") from exc
        if not content or len(content) > self.max_report_bytes:
            raise InvalidReportError("証跡sizeが不正です")
        checksum = hashlib.sha256(content).hexdigest()
        if checksum != path.stem:
            raise InvalidReportError("証跡checksumが一致しません")
        try:
            payload = json.loads(
                content.decode("utf-8", errors="strict"), object_pairs_hook=unique_object
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidReportError("証跡JSONが不正です") from exc
        return sanitize_report(payload, checksum)

    def list_reports(self, limit: int = 100) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise ValueError("limitは1以上200以下です")
        directory = self._directory()
        if directory is None:
            return {
                "configured": self.configured,
                "valid_report_count": 0,
                "invalid_report_count": 0,
                "items": [],
            }
        reports = []
        invalid_count = 0
        for path in directory.iterdir():
            try:
                reports.append(self._read(path))
            except InvalidReportError:
                invalid_count += 1
        reports.sort(key=lambda item: (item["checked_at"], item["report_sha256"]), reverse=True)
        summaries = [
            {key: value for key, value in report.items() if key not in {"checks", "limitations"}}
            for report in reports[:limit]
        ]
        return {
            "configured": True,
            "valid_report_count": len(reports),
            "invalid_report_count": invalid_count,
            "items": summaries,
        }

    def get_report(self, report_sha256: str) -> dict[str, Any] | None:
        if not HEX_SHA256.fullmatch(report_sha256):
            return None
        directory = self._directory()
        if directory is None:
            return None
        path = directory / f"{report_sha256}.json"
        if not path.exists():
            return None
        return self._read(path)
