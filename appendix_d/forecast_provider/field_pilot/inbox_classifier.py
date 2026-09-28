"""既知header fingerprintと値の形でCSVを説明可能に分類する。"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..ingestion.processor import detect_stream_encoding
from .inbox_policy import InboxPolicy, SchemaRule

SAMPLE_ROWS = 100


@dataclass(frozen=True)
class Classification:
    status: str
    reason: str
    kind: str | None = None
    location_id: str | None = None
    target_date: str | None = None
    schema_id: str | None = None
    mapping_version: str | None = None
    pilot_scope_version: str | None = None
    pilot_intake_version: str | None = None
    encoding: str | None = None
    header_sha256: str | None = None

    @property
    def key(self) -> tuple[str, str, str] | None:
        if self.kind is None or self.location_id is None or self.target_date is None:
            return None
        return self.kind, self.location_id, self.target_date


def header_sha256(headers: tuple[str, ...]) -> str:
    # InventoryStructureProfilerと同じfingerprint定義を共有する。
    return hashlib.sha256(json.dumps(headers, ensure_ascii=False).encode("utf-8")).hexdigest()


def _match(rule: SchemaRule, headers: tuple[str, ...], samples: list[dict]) -> str | None:
    if not set(rule.required_columns).issubset(headers) or not samples:
        return None
    dates = set()
    for row in samples:
        raw_date = (row.get(rule.date_column) or "").strip()
        try:
            dates.add(datetime.strptime(raw_date, rule.date_format).date().isoformat())
        except ValueError:
            return None
        if rule.quantity_column:
            try:
                quantity = Decimal((row.get(rule.quantity_column) or "").strip())
            except InvalidOperation:
                return None
            if not quantity.is_finite() or quantity < 0:
                return None
        if rule.location_column and (
            row.get(rule.location_column) or ""
        ).strip() != rule.location_id:
            return None
    return next(iter(dates)) if len(dates) == 1 else None


def classify_file(path: Path, original_name: str, policy: InboxPolicy) -> Classification:
    extension = Path(original_name).suffix.lower()
    with path.open("rb") as stream:
        magic = stream.read(8)
        stream.seek(0)
        if magic.startswith(b"%PDF-"):
            return Classification(
                "REVIEW_REQUIRED" if extension == ".pdf" else "REJECTED",
                "PDF_HUMAN_REVIEW_REQUIRED" if extension == ".pdf" else "EXTENSION_MISMATCH",
            )
        if extension != ".csv" or b"\x00" in magic:
            return Classification("REJECTED", "FORMAT_UNSUPPORTED")
        encoding, error = detect_stream_encoding(stream)
    if error or encoding is None:
        return Classification("REVIEW_REQUIRED", "ENCODING_UNKNOWN")
    try:
        with path.open("r", encoding=encoding, errors="strict", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            headers = tuple(reader.fieldnames or ())
            if not headers or len(headers) != len(set(headers)) or any(not col for col in headers):
                return Classification("REVIEW_REQUIRED", "HEADER_INVALID")
            fingerprint = header_sha256(headers)
            rules = [rule for rule in policy.rules if rule.header_sha256 == fingerprint]
            if not rules:
                return Classification(
                    "REVIEW_REQUIRED" if any(
                        set(rule.required_columns).issubset(headers) for rule in policy.rules
                    ) else "UNKNOWN",
                    "HEADER_CHANGED" if any(
                        set(rule.required_columns).issubset(headers) for rule in policy.rules
                    ) else "SCHEMA_UNKNOWN",
                    encoding=encoding, header_sha256=fingerprint,
                )
            samples = []
            for index, row in enumerate(reader):
                if index == SAMPLE_ROWS:
                    break
                if None in row or any(value is None for value in row.values()):
                    return Classification("REVIEW_REQUIRED", "ROW_SHAPE_INVALID")
                samples.append(row)
    except (OSError, UnicodeDecodeError, csv.Error):
        return Classification("REVIEW_REQUIRED", "CSV_INVALID")
    matches = [(rule, date) for rule in rules if (date := _match(rule, headers, samples))]
    if len(matches) != 1:
        return Classification(
            "REVIEW_REQUIRED", "SCHEMA_AMBIGUOUS" if matches else "VALUE_INVALID",
            encoding=encoding, header_sha256=fingerprint,
        )
    rule, date = matches[0]
    return Classification(
        "CONFIRMED", "KNOWN_SCHEMA", rule.kind, rule.location_id, date,
        rule.schema_id, rule.mapping_version, rule.pilot_scope_version,
        rule.pilot_intake_version, encoding, fingerprint,
    )
