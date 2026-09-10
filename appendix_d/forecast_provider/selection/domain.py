"""候補算出jobと確定選定版の検証・内容アドレス化。"""

import hashlib
import json
from datetime import UTC, datetime

from .contracts import CandidateJob, SelectionVersion

FORMAT_VERSION = 1


def make_candidate_job(definition: dict) -> CandidateJob:
    required = {
        "candidate_version",
        "daily_build_id",
        "business_product_ids",
        "max_missing_rate",
        "stable_cv_max",
        "intermittent_zero_rate_min",
        "requested_by",
        "purpose",
    }
    if set(definition) != required:
        raise ValueError("候補算出job定義の項目が契約と一致しません")
    _required(
        candidate_version=definition["candidate_version"],
        daily_build_id=definition["daily_build_id"],
        requested_by=definition["requested_by"],
        purpose=definition["purpose"],
    )
    business_ids = definition["business_product_ids"]
    if (
        not isinstance(business_ids, list)
        or len(business_ids) != len(set(business_ids))
        or not all(isinstance(value, str) and value for value in business_ids)
    ):
        raise ValueError("business_product_idsは重複のない文字列listです")
    _rate("max_missing_rate", definition["max_missing_rate"])
    _rate("intermittent_zero_rate_min", definition["intermittent_zero_rate_min"])
    stable = definition["stable_cv_max"]
    if isinstance(stable, bool) or not isinstance(stable, (int, float)) or stable < 0:
        raise ValueError("stable_cv_maxは0以上です")
    normalized = {
        **definition,
        "business_product_ids": sorted(business_ids),
        "max_missing_rate": float(definition["max_missing_rate"]),
        "stable_cv_max": float(stable),
        "intermittent_zero_rate_min": float(definition["intermittent_zero_rate_min"]),
    }
    fingerprint = _digest(normalized)
    return CandidateJob(
        f"selection-candidates-{fingerprint}",
        FORMAT_VERSION,
        fingerprint,
        normalized,
        "QUEUED",
    )


def make_selection(definition: dict) -> SelectionVersion:
    required = {
        "selection_version",
        "candidate_job_id",
        "scope",
        "items",
        "selected_by",
        "rationale",
    }
    if set(definition) != required:
        raise ValueError("選定版定義の項目が契約と一致しません")
    _required(
        selection_version=definition["selection_version"],
        candidate_job_id=definition["candidate_job_id"],
        selected_by=definition["selected_by"],
        rationale=definition["rationale"],
    )
    scope = definition["scope"]
    if scope not in {"INITIAL", "FULL"}:
        raise ValueError("scopeはINITIALまたはFULLです")
    items = definition["items"]
    limits = (3, 5) if scope == "INITIAL" else (20, 50)
    if not isinstance(items, list) or not limits[0] <= len(items) <= limits[1]:
        raise ValueError(f"{scope}の選定品目数は{limits[0]}〜{limits[1]}件です")
    normalized_items = []
    product_ids = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "canonical_product_id",
            "center_ids",
            "reason",
        }:
            raise ValueError("選定品目の項目が契約と一致しません")
        _required(canonical_product_id=item["canonical_product_id"], reason=item["reason"])
        product_id = item["canonical_product_id"]
        if product_id in product_ids:
            raise ValueError("選定品目は重複できません")
        product_ids.add(product_id)
        centers = item["center_ids"]
        if (
            not isinstance(centers, list)
            or not centers
            or len(centers) != len(set(centers))
            or not all(isinstance(value, str) and value for value in centers)
        ):
            raise ValueError("center_idsは重複のない非空文字列listです")
        normalized_items.append({**item, "center_ids": sorted(centers)})
    normalized = {
        **definition,
        "items": sorted(normalized_items, key=lambda item: item["canonical_product_id"]),
    }
    fingerprint = _digest(normalized)
    return SelectionVersion(
        f"selection-{fingerprint}",
        FORMAT_VERSION,
        fingerprint,
        normalized,
        datetime.now(UTC).isoformat(),
    )


def _rate(name: str, value) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"{name}は0以上1以下です")


def _required(**values) -> None:
    empty = [name for name, value in values.items() if not isinstance(value, str) or not value]
    if empty:
        raise ValueError(f"必須項目が空です: {', '.join(empty)}")


def _digest(value: dict) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
