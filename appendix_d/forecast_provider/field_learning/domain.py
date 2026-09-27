"""System参考値、担当者判断、後日実績を混同しない追記型domain。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from ..inventory_foundation.domain import canonical_datetime, canonical_decimal, validate_jan
from .contracts import FieldMode, OperatorDecision, OperatorReasonCode


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label}は必須です")
    return normalized


def _quantity(
    value: Decimal | int | str | None, label: str, *, required: bool = False
) -> Decimal | None:
    if value is None:
        if required:
            raise ValueError(f"{label}は必須です")
        return None
    normalized = Decimal(canonical_decimal(value))
    if normalized < 0:
        raise ValueError(f"{label}は0以上です")
    return normalized


def _known_and_recorded(known_at: datetime, recorded_at: datetime) -> tuple[datetime, datetime]:
    canonical_datetime(known_at, "known_at")
    canonical_datetime(recorded_at, "recorded_at")
    known = known_at.astimezone(UTC)
    recorded = recorded_at.astimezone(UTC)
    if known > recorded:
        raise ValueError("known_atはrecorded_at以前です")
    return known, recorded


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class FieldReferenceCase:
    case_id: str
    business_date: date
    jan: str
    canonical_product_id: str
    warehouse_id: str
    forecast_center_id: str
    forecast_run_id: str
    inventory_snapshot_id: str
    pilot_scope_version: str
    identity_bridge_version: str
    system_forecast_quantity: Decimal
    system_reference_quantity: Decimal
    policy_version: str
    mode: FieldMode
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


@dataclass(frozen=True)
class FieldOperatorDecisionEvent:
    decision_event_id: str
    case_id: str
    revision: int
    operator_decision: OperatorDecision
    operator_quantity: Decimal | None
    operator_reason_code: OperatorReasonCode | None
    operator_comment: str | None
    subject: str
    known_at: datetime
    recorded_at: datetime


@dataclass(frozen=True)
class FieldActualOutcomeEvent:
    actual_event_id: str
    case_id: str
    revision: int
    source_version: str
    source_sha256: str
    actual_shipped_quantity: Decimal | None
    actual_demand_quantity: Decimal | None
    stockout_quantity: Decimal | None
    expired_quantity: Decimal | None
    interwarehouse_transfer_quantity: Decimal | None
    known_at: datetime
    recorded_at: datetime
    content_sha256: str


class FieldLearningConflict(ValueError):
    pass


def build_reference_case(
    *,
    business_date: date,
    jan: str,
    canonical_product_id: str,
    warehouse_id: str,
    forecast_center_id: str,
    forecast_run_id: str,
    inventory_snapshot_id: str,
    pilot_scope_version: str,
    identity_bridge_version: str,
    system_forecast_quantity: Decimal | int | str,
    system_reference_quantity: Decimal | int | str,
    policy_version: str,
    mode: FieldMode,
    known_at: datetime,
    recorded_at: datetime,
) -> FieldReferenceCase:
    if isinstance(business_date, datetime) or not isinstance(business_date, date):
        raise ValueError("business_dateはdateです")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    normalized = {
        "jan": validate_jan(jan),
        "canonical_product_id": _required(canonical_product_id, "canonical_product_id"),
        "warehouse_id": _required(warehouse_id, "warehouse_id"),
        "forecast_center_id": _required(forecast_center_id, "forecast_center_id"),
        "forecast_run_id": _required(forecast_run_id, "forecast_run_id"),
        "inventory_snapshot_id": _required(inventory_snapshot_id, "inventory_snapshot_id"),
        "pilot_scope_version": _required(pilot_scope_version, "pilot_scope_version"),
        "identity_bridge_version": _required(identity_bridge_version, "identity_bridge_version"),
        "policy_version": _required(policy_version, "policy_version"),
    }
    forecast = _quantity(system_forecast_quantity, "system_forecast_quantity", required=True)
    reference = _quantity(system_reference_quantity, "system_reference_quantity", required=True)
    if not isinstance(mode, FieldMode):
        raise ValueError("modeが不正です")
    payload = {
        "format_version": "field-reference-case-v1",
        "business_date": business_date.isoformat(),
        **normalized,
        "system_forecast_quantity": canonical_decimal(forecast),
        "system_reference_quantity": canonical_decimal(reference),
        "mode": mode.value,
        "known_at": canonical_datetime(known),
    }
    content_sha256 = _digest(payload)
    return FieldReferenceCase(
        f"field-case-{content_sha256}",
        business_date,
        normalized["jan"],
        normalized["canonical_product_id"],
        normalized["warehouse_id"],
        normalized["forecast_center_id"],
        normalized["forecast_run_id"],
        normalized["inventory_snapshot_id"],
        normalized["pilot_scope_version"],
        normalized["identity_bridge_version"],
        forecast,
        reference,
        normalized["policy_version"],
        mode,
        known,
        recorded,
        content_sha256,
    )


def build_operator_decision_event(
    *,
    case: FieldReferenceCase,
    expected_revision: int,
    operator_decision: OperatorDecision,
    operator_quantity: Decimal | int | str | None,
    operator_reason_code: OperatorReasonCode | None,
    operator_comment: str | None,
    subject: str,
    known_at: datetime,
    recorded_at: datetime,
) -> FieldOperatorDecisionEvent:
    if isinstance(expected_revision, bool) or expected_revision < 0:
        raise ValueError("expected_revisionは0以上です")
    if not isinstance(operator_decision, OperatorDecision):
        raise ValueError("operator_decisionが不正です")
    quantity = _quantity(operator_quantity, "operator_quantity")
    comment = None if operator_comment is None else operator_comment.strip()
    if comment == "":
        comment = None
    if comment is not None and len(comment) > 500:
        raise ValueError("operator_commentは500文字以下です")
    if operator_reason_code is not None and not isinstance(
        operator_reason_code, OperatorReasonCode
    ):
        raise ValueError("operator_reason_codeが不正です")
    if operator_decision is OperatorDecision.ACCEPTED:
        if quantity != case.system_reference_quantity:
            raise ValueError("ACCEPTEDの数量はsystem referenceと一致させてください")
    elif operator_decision is OperatorDecision.INCREASED:
        if quantity is None or quantity <= case.system_reference_quantity:
            raise ValueError("INCREASEDの数量はsystem referenceより大きくしてください")
    elif operator_decision is OperatorDecision.DECREASED:
        if quantity is None or quantity >= case.system_reference_quantity:
            raise ValueError("DECREASEDの数量はsystem reference未満にしてください")
    elif operator_decision is OperatorDecision.NO_ACTION and quantity != Decimal("0"):
        raise ValueError("NO_ACTIONの数量は確定ゼロです")
    if (
        operator_decision
        in {
            OperatorDecision.INCREASED,
            OperatorDecision.DECREASED,
            OperatorDecision.REJECTED,
        }
        and operator_reason_code is None
    ):
        raise ValueError("変更または不採用にはreason codeが必要です")
    if operator_reason_code is OperatorReasonCode.OTHER and comment is None:
        raise ValueError("OTHERにはoperator_commentが必要です")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    subject = _required(subject, "subject")
    revision = expected_revision + 1
    payload = {
        "case_id": case.case_id,
        "revision": revision,
        "operator_decision": operator_decision.value,
        "operator_quantity": None if quantity is None else canonical_decimal(quantity),
        "operator_reason_code": None
        if operator_reason_code is None
        else operator_reason_code.value,
        "operator_comment": comment,
        "subject": subject,
        "known_at": canonical_datetime(known),
        "recorded_at": canonical_datetime(recorded),
    }
    return FieldOperatorDecisionEvent(
        f"field-decision-{_digest(payload)}",
        case.case_id,
        revision,
        operator_decision,
        quantity,
        operator_reason_code,
        comment,
        subject,
        known,
        recorded,
    )


def build_actual_outcome_event(
    *,
    case_id: str,
    expected_revision: int,
    source_version: str,
    source_sha256: str,
    actual_shipped_quantity: Decimal | int | str | None,
    actual_demand_quantity: Decimal | int | str | None,
    stockout_quantity: Decimal | int | str | None,
    expired_quantity: Decimal | int | str | None,
    interwarehouse_transfer_quantity: Decimal | int | str | None,
    known_at: datetime,
    recorded_at: datetime,
) -> FieldActualOutcomeEvent:
    case_id = _required(case_id, "case_id")
    source_version = _required(source_version, "source_version")
    if isinstance(expected_revision, bool) or expected_revision < 0:
        raise ValueError("expected_revisionは0以上です")
    if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256):
        raise ValueError("source_sha256は64文字のSHA-256です")
    quantities = tuple(
        _quantity(value, label)
        for value, label in (
            (actual_shipped_quantity, "actual_shipped_quantity"),
            (actual_demand_quantity, "actual_demand_quantity"),
            (stockout_quantity, "stockout_quantity"),
            (expired_quantity, "expired_quantity"),
            (interwarehouse_transfer_quantity, "interwarehouse_transfer_quantity"),
        )
    )
    if all(value is None for value in quantities):
        raise ValueError("Actual outcomeは少なくとも1つの数量が必要です")
    known, recorded = _known_and_recorded(known_at, recorded_at)
    revision = expected_revision + 1
    payload = {
        "format_version": "field-actual-outcome-v1",
        "case_id": case_id,
        "revision": revision,
        "source_version": source_version,
        "source_sha256": source_sha256,
        "quantities": [None if value is None else canonical_decimal(value) for value in quantities],
        "known_at": canonical_datetime(known),
    }
    content_sha256 = _digest(payload)
    return FieldActualOutcomeEvent(
        f"field-actual-{content_sha256}",
        case_id,
        revision,
        source_version,
        source_sha256,
        *quantities,
        known,
        recorded,
        content_sha256,
    )
