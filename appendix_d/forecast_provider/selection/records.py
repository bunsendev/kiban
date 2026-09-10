"""選定台帳のDB行と永続契約を変換する。"""

import json
from decimal import Decimal

from .contracts import CandidateJob, SelectionCandidate, SelectionItem, SelectionVersion


def encode_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def job_from_row(row) -> CandidateJob:
    return CandidateJob(
        row["candidate_job_id"],
        row["format_version"],
        row["condition_fingerprint"],
        json.loads(row["definition_json"]),
        row["status"],
        row["error"],
    )


def candidate_from_row(row) -> SelectionCandidate:
    return SelectionCandidate(
        row["candidate_job_id"],
        row["canonical_product_id"],
        row["rank"],
        Decimal(row["total_quantity"]),
        _decimal(row["quantity_share"]),
        _decimal(row["coefficient_of_variation"]),
        _decimal(row["zero_rate"]),
        _decimal(row["missing_rate"]),
        row["usable_days"],
        row["handled_days"],
        bool(row["jan_changed"]),
        bool(row["business_designated"]),
        tuple(json.loads(row["center_ids_json"])),
        tuple(json.loads(row["tags_json"])),
        bool(row["eligible"]),
        row["ineligibility_reason"],
    )


def selection_from_row(row) -> SelectionVersion:
    return SelectionVersion(
        row["selection_id"],
        row["format_version"],
        row["condition_fingerprint"],
        json.loads(row["definition_json"]),
        row["selected_at"],
    )


def item_from_row(row) -> SelectionItem:
    return SelectionItem(
        row["selection_id"],
        row["canonical_product_id"],
        tuple(json.loads(row["center_ids_json"])),
        row["reason"],
    )


def _decimal(value) -> Decimal | None:
    return None if value is None else Decimal(value)
