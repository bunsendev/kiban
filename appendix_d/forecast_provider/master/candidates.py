"""正規化済み行から監査表示用のJAN候補を生成する。"""

import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from itertools import combinations

from .contracts import MatchingCandidate
from .names import name_similarity, normalize_product_name


def generate_candidates(job: object, rows: list[dict]) -> list[MatchingCandidate]:
    grouped = _group(rows)
    output = []
    definition = job.definition
    for left_jan, right_jan in combinations(sorted(grouped), 2):
        left = grouped[left_jan]
        right = grouped[right_jan]
        similarity = name_similarity(left["name"], right["name"])
        left, right = _chronological(left, right)
        coexistence = _coexistence_days(left, right)
        gap = max(0, (right["first_date"] - left["last_date"]).days - 1)
        reasons = []
        if normalize_product_name(left["name"]) == normalize_product_name(right["name"]):
            reasons.append("SAME_NORMALIZED_NAME")
        elif similarity >= definition["similarity_threshold"]:
            reasons.append("SIMILAR_NAME")
        if coexistence == 0 and gap <= definition["max_handoff_gap_days"]:
            reasons.append("DATE_HANDOFF")
        handoff_candidate = (
            "DATE_HANDOFF" in reasons and similarity >= definition["handoff_similarity_threshold"]
        )
        if similarity < definition["similarity_threshold"] and not handoff_candidate:
            continue
        details = {
            "policy_version": definition["policy_version"],
            "left_name": left["name"],
            "right_name": right["name"],
            "name_similarity": round(similarity, 6),
            "left_first_date": left["first_date"].isoformat(),
            "left_last_date": left["last_date"].isoformat(),
            "right_first_date": right["first_date"].isoformat(),
            "right_last_date": right["last_date"].isoformat(),
            "coexistence_days": coexistence,
            "gap_days": gap,
            "left_units": sorted(left["units"]),
            "right_units": sorted(right["units"]),
            "left_center_quantities": _quantities(left["centers"]),
            "right_center_quantities": _quantities(right["centers"]),
            "left_center_daily_quantities": _daily_quantities(left["daily"]),
            "right_center_daily_quantities": _daily_quantities(right["daily"]),
            "reasons": reasons,
        }
        payload = json.dumps(
            [job.matching_job_id, left["jan"], right["jan"], details],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        candidate_id = f"candidate-{hashlib.sha256(payload.encode()).hexdigest()}"
        output.append(
            MatchingCandidate(candidate_id, job.matching_job_id, left["jan"], right["jan"], details)
        )
    return output


def _group(rows):
    values = {}
    names = defaultdict(Counter)
    for row in rows:
        jan = row["raw_jan"]
        names[jan][row["raw_product_name"]] += 1
        item = values.setdefault(
            jan,
            {
                "jan": jan,
                "first_date": date.fromisoformat(row["shipment_date"]),
                "last_date": date.fromisoformat(row["shipment_date"]),
                "units": set(),
                "centers": defaultdict(Decimal),
                "daily": defaultdict(Decimal),
            },
        )
        observed = date.fromisoformat(row["shipment_date"])
        item["first_date"] = min(item["first_date"], observed)
        item["last_date"] = max(item["last_date"], observed)
        item["units"].add(row["unit"])
        item["centers"][row["center_id"]] += Decimal(row["quantity"])
        item["daily"][(row["center_id"], row["shipment_date"])] += Decimal(row["quantity"])
    for jan, item in values.items():
        item["name"] = sorted(names[jan].items(), key=lambda pair: (-pair[1], pair[0]))[0][0]
    return values


def _chronological(left, right):
    if (left["first_date"], left["jan"]) <= (right["first_date"], right["jan"]):
        return left, right
    return right, left


def _coexistence_days(left, right):
    start = max(left["first_date"], right["first_date"])
    end = min(left["last_date"], right["last_date"])
    return max(0, (end - start).days + 1)


def _quantities(values):
    return {key: str(value) for key, value in sorted(values.items())}


def _daily_quantities(values):
    output = defaultdict(list)
    for (center_id, observed), quantity in sorted(values.items()):
        output[center_id].append({"date": observed, "quantity": str(quantity)})
    return dict(output)
