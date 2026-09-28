"""承認済みの構造だけを認識に利用し、正式データ採用とは分離する。"""

from __future__ import annotations

import csv
import hashlib
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from .inbox_classifier import Classification, _match, classify_file
from .inbox_ledger import InboxLedger
from .inbox_policy import KINDS, InboxPolicy, InboxPolicyError, SchemaRule, load_inbox_policy
from .learning_candidate import inspect_learning_candidate
from .learning_store import LearningStore

logger = logging.getLogger("kiban.field_pilot.learning")
OPERATOR_KINDS = KINDS | {"OTHER"}
MAX_ARCHIVE_BYTES = 2_000_000_000


def _valid_date(value: str, date_format: str) -> bool:
    try:
        datetime.strptime(value, date_format)
        return True
    except ValueError:
        return False


class LearningService:
    def __init__(self, inbox_root: Path, policy_path: Path):
        self.root = inbox_root.resolve(strict=True)
        self.policy_path = policy_path
        self.store = LearningStore(self.root / "inbox.sqlite3")

    def base_policy(self) -> InboxPolicy:
        try:
            return load_inbox_policy(self.policy_path)
        except InboxPolicyError:
            return InboxPolicy("UNCONFIGURED", (), ())

    def recognition_policy(self) -> InboxPolicy:
        base = self.base_policy()
        return replace(base, rules=base.rules + self.store.active_rules())

    def consider(
        self, classification: Classification, archive: Path, reference: str,
    ) -> str | None:
        if classification.status not in {"UNKNOWN", "REVIEW_REQUIRED"}:
            return None
        proposal = inspect_learning_candidate(archive, classification, self.recognition_policy())
        if proposal is None:
            return None
        return self.store.add_candidate(proposal, self.base_policy().version, reference)

    @staticmethod
    def _public(candidate: dict) -> dict:
        structure = candidate["structure"]
        return {
            "candidate_id": candidate["candidate_id"],
            "status": candidate["status"],
            "suggested_kind": structure["suggested_kind"],
            "confidence": structure["confidence"],
            "risk": structure["risk"],
            "columns": structure["columns"],
            "headers": structure["headers"],
            "confirmed_kind": candidate["confirmed_kind"],
        }

    def pending_view(self) -> dict:
        pending = [
            self._public(item) for item in self.store.list_candidates()
            if item["status"] == "PENDING_OPERATOR"
        ]
        return {"pending_count": len(pending), "candidates": pending}

    def admin_view(self) -> dict:
        return {
            "candidates": [self._public(item) for item in self.store.list_candidates()],
            "contracts": self.store.list_contracts(),
            "events": self.store.list_events(),
        }

    def _archive(self, candidate: dict) -> Path:
        archive_root = self.root / "Archive"
        reference = Path(candidate["archive_reference"])
        if reference.is_absolute() or ".." in reference.parts or len(reference.parts) != 3:
            raise ValueError("LEARNING_ARCHIVE_INVALID")
        digest = reference.parts[1]
        if len(digest) != 64 or reference.parts[0] != digest[:2]:
            raise ValueError("LEARNING_ARCHIVE_INVALID")
        path = (archive_root / reference).resolve(strict=True)
        path.relative_to(archive_root.resolve(strict=True))
        if not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("LEARNING_ARCHIVE_INVALID")
        actual = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                actual.update(block)
        if actual.hexdigest() != digest:
            raise ValueError("LEARNING_ARCHIVE_INVALID")
        return path

    def _check_rule(self, candidate: dict, rule: SchemaRule) -> None:
        structure = candidate["structure"]
        headers = tuple(structure["headers"])
        if not set(rule.required_columns).issubset(headers):
            raise ValueError("LEARNING_COLUMNS_INVALID")
        result = classify_file(
            self._archive(candidate), Path(candidate["archive_reference"]).name,
            InboxPolicy(candidate["policy_version"], (), (rule,)),
        )
        if result.status != "CONFIRMED":
            raise ValueError("LEARNING_VALIDATION_FAILED")
        try:
            with self._archive(candidate).open(
                "r", encoding=structure["encoding"], errors="strict", newline="",
            ) as stream:
                reader = csv.DictReader(stream, strict=True)
                if tuple(reader.fieldnames or ()) != headers:
                    raise ValueError("LEARNING_VALIDATION_FAILED")
                target_date = result.target_date
                for row in reader:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError("LEARNING_VALIDATION_FAILED")
                    if _match(rule, headers, [row]) != target_date:
                        raise ValueError("LEARNING_VALIDATION_FAILED")
                    if rule.jan_column and not (row[rule.jan_column] or "").strip():
                        raise ValueError("LEARNING_VALIDATION_FAILED")
                    if rule.expiry_column:
                        expiry = (row[rule.expiry_column] or "").strip()
                        if not any(
                            _valid_date(expiry, date_format)
                            for date_format in ("%Y-%m-%d", "%Y/%m/%d")
                        ):
                            raise ValueError("LEARNING_VALIDATION_FAILED")
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise ValueError("LEARNING_VALIDATION_FAILED") from exc

    def _inherited_rule(self, candidate: dict, kind: str) -> SchemaRule | None:
        structure = candidate["structure"]
        parent = structure["parent_schema_id"]
        if not parent or structure["risk"] != "LOW" or structure["suggested_kind"] != kind:
            return None
        base = next(
            (rule for rule in self.recognition_policy().rules if rule.schema_id == parent),
            None,
        )
        if base is None:
            return None
        rule = replace(
            base, schema_id="learned-" + candidate["candidate_id"][:24],
            header_sha256=structure["header_sha256"],
        )
        self._check_rule(candidate, rule)
        return rule

    def operator_decide(
        self, candidate_id: str, kind: str, *, disagree: bool = False,
        actor: str = "FIELD_PILOT_OPERATOR",
    ) -> dict:
        if kind not in OPERATOR_KINDS:
            raise ValueError("LEARNING_KIND_INVALID")
        candidate = self.store.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError("LEARNING_CANDIDATE_NOT_FOUND")
        if candidate["status"] != "PENDING_OPERATOR":
            if candidate["confirmed_kind"] == kind:
                return self._public(candidate)
            raise ValueError("LEARNING_ALREADY_DECIDED")
        try:
            rule = None if disagree else self._inherited_rule(candidate, kind)
        except ValueError:
            self.store.validation_failed(candidate_id, actor)
            raise
        result = self.store.decide(
            candidate_id, actor=actor,
            action="DISAGREE" if disagree else "OPERATOR_CONFIRM", kind=kind,
            rule=rule, source_unit=candidate["structure"].get("source_unit"),
            normalized_unit="CASE" if rule else None,
        )
        if rule:
            self._reclassify(result)
        return self._public(result)

    def admin_approve(self, candidate_id: str, kind: str, fields: dict, actor: str) -> dict:
        if kind not in KINDS or not actor or len(actor) > 120:
            raise ValueError("LEARNING_ADMIN_INPUT_INVALID")
        candidate = self.store.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError("LEARNING_CANDIDATE_NOT_FOUND")
        if candidate["status"] == "ACTIVE" and candidate["confirmed_kind"] == kind:
            return self._public(candidate)
        headers = set(candidate["structure"]["headers"])
        allowed_formats = {"%Y-%m-%d", "%Y/%m/%d"}
        date_column = fields.get("date_column")
        quantity_column = fields.get("quantity_column")
        location_column = fields.get("location_column")
        jan_column = fields.get("jan_column")
        expiry_column = fields.get("expiry_column")
        source_unit = fields.get("source_unit")
        location_id = fields.get("location_id")
        if (
            date_column not in headers or quantity_column not in headers
            or fields.get("date_format") not in allowed_formats
            or not isinstance(location_id, str) or not 0 < len(location_id) <= 120
            or not isinstance(source_unit, str) or not 0 < len(source_unit) <= 120
            or fields.get("normalized_unit") != "CASE"
            or (location_column is not None and location_column not in headers)
            or (jan_column is not None and jan_column not in headers)
            or (expiry_column is not None and expiry_column not in headers)
            or (kind in {"WAREHOUSE_INVENTORY", "FACTORY_INVENTORY"}
                and (jan_column is None or expiry_column is None))
            or (kind, location_id) not in {item.key for item in self.base_policy().required}
        ):
            raise ValueError("LEARNING_ADMIN_INPUT_INVALID")
        columns = tuple(dict.fromkeys(filter(None, (
            date_column, quantity_column, location_column, jan_column, expiry_column,
        ))))
        rule = SchemaRule(
            schema_id="learned-" + candidate_id[:24], kind=kind,
            location_id=location_id,
            header_sha256=candidate["structure"]["header_sha256"],
            required_columns=columns, date_column=date_column,
            date_format=fields["date_format"], quantity_column=quantity_column,
            location_column=location_column,
            mapping_version=fields.get("mapping_version"),
            pilot_scope_version=None, pilot_intake_version=None,
            jan_column=jan_column, expiry_column=expiry_column,
            source_unit=source_unit, normalized_unit="CASE",
        )
        try:
            self._check_rule(candidate, rule)
        except ValueError:
            self.store.validation_failed(candidate_id, actor)
            raise
        result = self.store.decide(
            candidate_id, actor=actor, action="ADMIN_APPROVE", kind=kind,
            rule=rule, source_unit=source_unit, normalized_unit="CASE",
        )
        self._reclassify(result)
        return self._public(result)

    def admin_reject(self, candidate_id: str, actor: str) -> dict:
        candidate = self.store.get_candidate(candidate_id)
        if candidate is None:
            raise ValueError("LEARNING_CANDIDATE_NOT_FOUND")
        result = self.store.decide(
            candidate_id, actor=actor, action="ADMIN_REJECT",
            kind=candidate["confirmed_kind"] or "OTHER",
        )
        return self._public(result)

    def admin_deactivate(self, version: str, actor: str) -> None:
        if not actor or len(actor) > 120:
            raise ValueError("LEARNING_ADMIN_INPUT_INVALID")
        self.store.deactivate(version, actor)

    def _reclassify(self, candidate: dict) -> None:
        try:
            archive = self._archive(candidate)
            policy = self.recognition_policy()
            result = classify_file(archive, archive.name, policy)
            if result.status != "CONFIRMED":
                return
            digest = archive.parent.name
            InboxLedger(self.root / "inbox.sqlite3").record(
                stage_id=uuid.uuid4().hex, sha256=digest,
                source_name_sha256=hashlib.sha256(archive.name.encode()).hexdigest(),
                size_bytes=archive.stat().st_size, status="RECEIVED",
                reason="LEARNED_STRUCTURE_AWAITING_FORMAL_IMPORT",
                classification=result, policy_version=self.base_policy().version,
                archive_reference=candidate["archive_reference"],
                received_at=datetime.now(UTC).isoformat(),
            )
        except (OSError, ValueError):
            logger.warning("learned file reclassification unavailable")
