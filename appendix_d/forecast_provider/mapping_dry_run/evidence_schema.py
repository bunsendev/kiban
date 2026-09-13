"""mappingドライラン証跡の部分schema検証。"""

from __future__ import annotations

import re
from typing import Any

from .contracts import CHECK_IDS, SUITE_ID, DryRunLimits
from .inspector import QUARANTINE_REASON_CODES

HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAPPING_ID = re.compile(r"^map-[0-9a-f]{64}$")


class InvalidReportError(ValueError):
    """checksumまたは固定schemaが一致しない証跡。"""


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise InvalidReportError("JSON keyが重複しています")
        value[key] = item
    return value


def validate_conditions(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not {"suite_id", "limits"} <= value.keys():
        raise InvalidReportError("実行条件が不正です")
    if set(value) - {"suite_id", "limits", "mapping_id", "source_sha256"}:
        raise InvalidReportError("実行条件に未知の項目があります")
    limits = value["limits"]
    if value["suite_id"] != SUITE_ID or not isinstance(limits, dict):
        raise InvalidReportError("実行条件が不正です")
    if set(limits) != {"sample_rows", "max_source_bytes", "max_mapping_bytes"}:
        raise InvalidReportError("実行上限が不正です")
    if any(type(item) is not int for item in limits.values()):
        raise InvalidReportError("実行上限が不正です")
    try:
        DryRunLimits(**limits)
    except (TypeError, ValueError) as exc:
        raise InvalidReportError("実行上限が不正です") from exc
    mapping_id = value.get("mapping_id")
    source_sha256 = value.get("source_sha256")
    if mapping_id is not None and (
        not isinstance(mapping_id, str) or not MAPPING_ID.fullmatch(mapping_id)
    ):
        raise InvalidReportError("mapping IDが不正です")
    if source_sha256 is not None and (
        not isinstance(source_sha256, str) or not HEX_SHA256.fullmatch(source_sha256)
    ):
        raise InvalidReportError("原本checksumが不正です")
    return value


def validate_checks(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 1 <= len(value) <= len(CHECK_IDS):
        raise InvalidReportError("判定一覧が不正です")
    output = []
    seen = set()
    required_keys = {"check_id", "status", "actual", "expected"}
    for item in value:
        if not isinstance(item, dict) or set(item) != required_keys:
            raise InvalidReportError("判定項目が不正です")
        check_id = item["check_id"]
        status = item["status"]
        if check_id not in CHECK_IDS or check_id in seen or status not in {"PASSED", "FAILED"}:
            raise InvalidReportError("判定項目が不正です")
        seen.add(check_id)
        output.append({"check_id": check_id, "status": status})
    return output


def validate_observations(value: Any) -> dict[str, Any]:
    empty = {
        "sampled_rows": 0,
        "accepted_rows": 0,
        "quarantined_rows": 0,
        "truncated": False,
        "quarantine_reason_counts": {},
    }
    if value == {}:
        return empty
    if not isinstance(value, dict) or set(value) != set(empty):
        raise InvalidReportError("観測結果が不正です")
    for key in ("sampled_rows", "accepted_rows", "quarantined_rows"):
        if type(value[key]) is not int or value[key] < 0:
            raise InvalidReportError("観測件数が不正です")
    if value["sampled_rows"] != value["accepted_rows"] + value["quarantined_rows"]:
        raise InvalidReportError("観測件数が一致しません")
    if type(value["truncated"]) is not bool:
        raise InvalidReportError("打切り状態が不正です")
    reasons = value["quarantine_reason_counts"]
    if not isinstance(reasons, dict) or any(
        key not in QUARANTINE_REASON_CODES or type(count) is not int or count < 0
        for key, count in reasons.items()
    ):
        raise InvalidReportError("隔離理由が不正です")
    return {**value, "quarantine_reason_counts": dict(sorted(reasons.items()))}
