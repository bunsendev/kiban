"""後日実績CSVを検証し、追記型Feedback台帳へ原子的に接続する。"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime

from ..field_learning.domain import FieldActualOutcomeEvent, build_actual_outcome_event
from ..inventory_foundation.domain import canonical_datetime

MAX_CSV_BYTES = 10 * 1024 * 1024
MAX_ROWS = 500
QUANTITY_COLUMNS = (
    "actual_shipped_quantity", "actual_demand_quantity", "stockout_quantity",
    "expired_quantity", "interwarehouse_transfer_quantity",
)
COLUMNS = ("case_id", "expected_revision", "unit", *QUANTITY_COLUMNS)


@dataclass(frozen=True)
class ActualImportPlan:
    source_version: str
    source_sha256: str
    known_at: datetime
    recorded_at: datetime
    events: tuple[FieldActualOutcomeEvent, ...]


class FieldActualImporter:
    def __init__(self, field_store):
        self.field_store = field_store

    def prepare(
        self, content: bytes, *, source_version: str, known_at: datetime,
        recorded_at: datetime,
    ) -> ActualImportPlan:
        """原本をDBへ書かずに全行検証する。空欄はNULL、文字列0は確定ゼロ。"""

        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_CSV_BYTES:
            raise ValueError("CSVは1 byte以上10 MiB以下です")
        if not source_version or not source_version.strip():
            raise ValueError("source_versionは必須です")
        canonical_datetime(known_at, "known_at")
        canonical_datetime(recorded_at, "recorded_at")
        if known_at > recorded_at:
            raise ValueError("known_atはrecorded_at以前です")
        try:
            decoded = content.decode("utf-8-sig", errors="strict")
        except UnicodeError as exc:
            raise ValueError("CSVはUTF-8で指定してください") from exc
        reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
        if reader.fieldnames != list(COLUMNS):
            raise ValueError("CSV列が契約と一致しません")
        rows = list(reader)
        if not 1 <= len(rows) <= MAX_ROWS:
            raise ValueError("CSVは1行以上500行以下です")
        digest = hashlib.sha256(content).hexdigest()
        events = []
        seen = set()
        for line, row in enumerate(rows, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV {line}行目の列数が不正です")
            case_id = row["case_id"].strip()
            if not case_id or case_id in seen:
                raise ValueError(f"CSV {line}行目のcase_idが空または重複です")
            seen.add(case_id)
            revision_text = row["expected_revision"].strip()
            if not revision_text.isascii() or not revision_text.isdigit():
                raise ValueError(f"CSV {line}行目のexpected_revisionが不正です")
            expected = int(revision_text)
            if row["unit"].strip() != "CASE":
                raise ValueError(f"CSV {line}行目のunitはCASEです")
            case = self.field_store.get_reference_case(case_id)
            if case is None:
                raise ValueError(f"CSV {line}行目のreference caseが存在しません")
            if known_at < case.known_at:
                raise ValueError(f"CSV {line}行目のknown_atがreferenceより前です")
            previous = self.field_store.list_actual_outcomes(case_id)
            current = 0 if not previous else previous[-1].revision
            if expected != current:
                raise ValueError(f"CSV {line}行目のexpected_revisionが台帳と不一致です")
            if previous and known_at < previous[-1].known_at:
                raise ValueError(f"CSV {line}行目の訂正known_atが前版より前です")
            quantities = {
                name: row[name].strip() or None for name in QUANTITY_COLUMNS
            }
            try:
                event = build_actual_outcome_event(
                    case_id=case_id, expected_revision=expected,
                    source_version=source_version.strip(), source_sha256=digest,
                    known_at=known_at, recorded_at=recorded_at, **quantities,
                )
            except ValueError as exc:
                raise ValueError(f"CSV {line}行目: {exc}") from exc
            events.append(event)
        return ActualImportPlan(
            source_version.strip(), digest, known_at, recorded_at, tuple(events)
        )

    def apply(self, plan: ActualImportPlan) -> tuple[FieldActualOutcomeEvent, ...]:
        """prepare後の並行更新もcommit時に検出する。"""

        return self.field_store.append_actual_outcomes_batch(plan.events)
