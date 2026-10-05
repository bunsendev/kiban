"""Source labels for the field screen; never infer quantities or identifiers."""

import csv
import io
import json
import zipfile
from collections import defaultdict

from .business_archive import _decode
from .business_review import latest_decisions, review_view
from .inventory_handoff import _latest_inventory_members, _mapped_jan


def source_metadata(paths, analysis_id):
    report = json.loads((paths.analysis / f"{analysis_id}.json").read_text("utf-8"))
    journal = paths.decisions / f"{analysis_id}.jsonl"
    decisions = latest_decisions(journal)
    names = defaultdict(set)
    with zipfile.ZipFile(paths.input / f"{analysis_id}.zip") as archive:
        for center, (member, _) in _latest_inventory_members(archive).items():
            for row in csv.DictReader(io.StringIO(_decode(archive.read(member)))):
                jan = _mapped_jan(report, decisions, str(row.get("商品コード") or "").strip())
                label = str(row.get("商品名") or "").strip()
                if jan and label:
                    names[(center, jan)].add(label)
    issues = []
    for issue in review_view(report, journal)["issues"]:
        decision = issue.get("decision") or {}
        if not decision or decision.get("action") == "EXCLUDE":
            issues.append(
                {
                    "source_value": issue["source_value"],
                    "name": issue.get("label", ""),
                    "reason": issue["reason"],
                    "rows": issue["count"],
                    "status": "対象から除外" if decision else "未確認",
                }
            )
    return names, issues
