"""比較結果を安全で決定的なUTF-8 BOM付きCSVへ変換する。"""

import csv
import hashlib
import io
import os
import uuid
from pathlib import Path

from ..catalog.contracts import SnapshotRecord
from ..evaluation_registry.contracts import ComparisonRecord, RunEvaluation

METRICS = ("wape_pct", "mae", "rmse", "bias", "bias_rate_pct", "under", "over")
COUNT_COLUMNS = (
    "run_planned_count",
    "run_success_count",
    "run_failure_count",
    "run_success_rate",
    "shared_planned_count",
    "shared_success_count",
    "shared_failure_count",
    "truth_eligible_count",
    "truth_missing_count",
    "truth_success_count",
    "common_success_count",
    "own_planned_count",
    "own_truth_eligible_count",
    "own_truth_missing_count",
    "own_success_count",
    "official_common_success_count",
)
HEADER = (
    "export_id",
    "export_version",
    "comparison_id",
    "comparison_set_id",
    "official_comparison_set_id",
    "truth_snapshot_id",
    "truth_version",
    "selection_version",
    "availability_mode",
    "evaluation_scope_hash",
    "mode",
    "horizon",
    "policy_version",
    "baseline_run_id",
    "run_id",
    "provider_id",
    "model_name",
    "conformance_id",
    "official_included",
    "incomplete",
    "official_planned_count",
    "official_truth_eligible_count",
    "official_truth_missing_count",
    *COUNT_COLUMNS,
    *(f"own_{name}" for name in METRICS),
    *(f"common_{name}" for name in METRICS),
    *(f"official_common_{name}" for name in METRICS),
    "baseline_improvement_pct",
    "baseline_wape_absolute_difference_pct",
    "metric_units",
    "comparison_purpose",
    "requested_by",
)


def render_comparison_csv(
    export_id: str,
    export_version: str,
    comparison: ComparisonRecord,
    evaluations: list[RunEvaluation],
    baseline_run_id: str,
    requested_by: str,
    snapshot: SnapshotRecord,
) -> bytes:
    by_run = {item.run_id: item for item in evaluations}
    if baseline_run_id not in by_run:
        raise ValueError("baseline runが比較結果に含まれません")
    result, definition = comparison.result, comparison.definition
    baseline_wape = _metric(by_run[baseline_run_id].score, "common_metrics", "wape_pct")
    official = set(result["official_runs"])
    incomplete = set(result["incomplete_runs"])
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(HEADER)
    for item in sorted(evaluations, key=lambda value: value.run_id):
        score = item.score
        wape = _metric(score, "common_metrics", "wape_pct")
        improvement, absolute = _improvement(baseline_wape, wape)
        row = [
            export_id,
            export_version,
            comparison.comparison_id,
            result["comparison_set_id"],
            result["official_comparison_set_id"],
            definition["truth_snapshot_id"],
            definition["truth_version"],
            snapshot.manifest["selection_version"],
            snapshot.manifest["availability_mode"],
            definition["evaluation_scope_hash"],
            definition["mode"],
            definition["horizon"],
            definition["policy_version"],
            baseline_run_id,
            item.run_id,
            item.provider_id,
            item.model_name,
            item.conformance_id,
            item.run_id in official,
            item.run_id in incomplete,
            result["official_planned_count"],
            result["official_truth_eligible_count"],
            result["official_truth_missing_count"],
            *(score.get(name) for name in COUNT_COLUMNS),
            *(_metric(score, "own_metrics", name) for name in METRICS),
            *(_metric(score, "common_metrics", name) for name in METRICS),
            *(_metric(score, "official_common_metrics", name) for name in METRICS),
            improvement,
            absolute,
            "wape_pct/bias_rate_pct/baseline_improvement_pct=percent;"
            "baseline_wape_absolute_difference_pct=percentage_point;"
            "mae/rmse/bias/under/over=quantity",
            definition["purpose"],
            requested_by,
        ]
        writer.writerow([_safe(value) for value in row])
    return stream.getvalue().encode("utf-8-sig")


def publish_csv(payload: bytes, output_root: Path) -> tuple[str, str]:
    checksum = hashlib.sha256(payload).hexdigest()
    target = output_root.resolve() / "comparisons" / f"{checksum}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != payload:
            raise ValueError("同じchecksumの比較CSV内容が一致しません")
    else:
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    return target.as_uri(), checksum


def _metric(score: dict, group: str, name: str):
    values = score.get(group)
    return None if values is None else values.get(name)


def _improvement(baseline, value) -> tuple[float | None, float | None]:
    if baseline is None or value is None:
        return None, None
    difference = float(baseline) - float(value)
    improvement = None if baseline == 0 else difference / float(baseline) * 100
    return improvement, difference


def _safe(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value
