"""現場Inboxの管理者承認済みschemaと日次必須集合。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MAX_POLICY_BYTES = 65_536
KINDS = frozenset({
    "SHIPMENT_ACTUAL", "WAREHOUSE_INVENTORY", "FACTORY_INVENTORY",
    "PRODUCTION_PLAN", "PRODUCTION_SCHEDULE",
})


@dataclass(frozen=True)
class RequiredInput:
    kind: str
    location_id: str
    display_name: str

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.location_id


@dataclass(frozen=True)
class SchemaRule:
    schema_id: str
    kind: str
    location_id: str
    header_sha256: str
    required_columns: tuple[str, ...]
    date_column: str
    date_format: str
    quantity_column: str | None
    location_column: str | None
    mapping_version: str | None
    pilot_scope_version: str | None
    pilot_intake_version: str | None
    jan_column: str | None = None
    expiry_column: str | None = None
    source_unit: str | None = None
    normalized_unit: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.location_id


@dataclass(frozen=True)
class InboxPolicy:
    version: str
    required: tuple[RequiredInput, ...]
    rules: tuple[SchemaRule, ...]


class InboxPolicyError(ValueError):
    pass


def _text(value: object, *, max_length: int = 120) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise InboxPolicyError("POLICY_INVALID")
    return value.strip()


def _optional(value: object) -> str | None:
    return None if value is None else _text(value)


def load_inbox_policy(path: Path) -> InboxPolicy:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_POLICY_BYTES:
            raise InboxPolicyError("POLICY_NOT_CONFIGURED")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("format") != "field-pilot-inbox-v1":
            raise InboxPolicyError("POLICY_INVALID")
        version = _text(payload.get("version"))
        raw_required = payload.get("required")
        raw_rules = payload.get("rules")
        if not isinstance(raw_required, list) or not isinstance(raw_rules, list):
            raise InboxPolicyError("POLICY_INVALID")
        required = tuple(
            RequiredInput(
                _text(item["kind"]), _text(item["location_id"]),
                _text(item["display_name"]),
            )
            for item in raw_required
        )
        rules = tuple(
            SchemaRule(
                _text(item["schema_id"]), _text(item["kind"]),
                _text(item["location_id"]), _text(item["header_sha256"], max_length=64),
                tuple(_text(column) for column in item["required_columns"]),
                _text(item["date_column"]), _text(item["date_format"]),
                _optional(item.get("quantity_column")),
                _optional(item.get("location_column")),
                _optional(item.get("mapping_version")),
                _optional(item.get("pilot_scope_version")),
                _optional(item.get("pilot_intake_version")),
                _optional(item.get("jan_column")),
                _optional(item.get("expiry_column")),
                _optional(item.get("source_unit")),
                _optional(item.get("normalized_unit")),
            )
            for item in raw_rules
        )
    except (
        OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError,
        AttributeError,
    ) as exc:
        raise InboxPolicyError("POLICY_INVALID") from exc
    if not required or not rules or len(required) > 50 or len(rules) > 100:
        raise InboxPolicyError("POLICY_NOT_CONFIGURED")
    if len({item.key for item in required}) != len(required):
        raise InboxPolicyError("POLICY_INVALID")
    if len({item.schema_id for item in rules}) != len(rules):
        raise InboxPolicyError("POLICY_INVALID")
    if not {item.key for item in required}.issubset({rule.key for rule in rules}):
        raise InboxPolicyError("POLICY_INVALID")
    if any(item.kind not in KINDS for item in (*required, *rules)):
        raise InboxPolicyError("POLICY_INVALID")
    if any(
        len(rule.header_sha256) != 64
        or any(char not in "0123456789abcdef" for char in rule.header_sha256)
        or not rule.required_columns
        or rule.date_column not in rule.required_columns
        or (rule.quantity_column and rule.quantity_column not in rule.required_columns)
        or (rule.location_column and rule.location_column not in rule.required_columns)
        or (rule.jan_column and rule.jan_column not in rule.required_columns)
        or (rule.expiry_column and rule.expiry_column not in rule.required_columns)
        or (rule.normalized_unit and rule.normalized_unit != "CASE")
        or (rule.pilot_scope_version is None) != (rule.pilot_intake_version is None)
        for rule in rules
    ):
        raise InboxPolicyError("POLICY_INVALID")
    return InboxPolicy(version, required, rules)
