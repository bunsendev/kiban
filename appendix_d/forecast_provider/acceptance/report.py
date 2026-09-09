"""受入品質レポートを内容アドレス方式で発行する。"""

import hashlib
import json
import os
import uuid
from pathlib import Path

from .contracts import AcceptanceCase, AcceptanceCheck, ReportOutcome


def publish_report(
    case: AcceptanceCase,
    checks: list[AcceptanceCheck],
    summary: dict,
    outcome: ReportOutcome,
    output_root: Path,
) -> tuple[str, str, str, str]:
    payload = {
        "format_version": 1,
        "case_id": case.case_id,
        "condition_fingerprint": case.condition_fingerprint,
        "definition": case.definition,
        "outcome": outcome,
        "summary": summary,
        "checks": [
            {
                "check_id": item.check_id,
                "status": item.status,
                "actual": item.actual,
                "expected": item.expected,
                "detail": item.detail,
            }
            for item in checks
        ],
    }
    json_bytes = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    markdown_bytes = _markdown(payload).encode()
    json_uri, json_sha = _publish(json_bytes, output_root, ".json")
    markdown_uri, markdown_sha = _publish(markdown_bytes, output_root, ".md")
    return json_uri, json_sha, markdown_uri, markdown_sha


def _publish(payload: bytes, output_root: Path, suffix: str) -> tuple[str, str]:
    checksum = hashlib.sha256(payload).hexdigest()
    target = output_root.resolve() / "acceptance" / f"{checksum}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != payload:
            raise ValueError("同じchecksumの受入レポート内容が一致しません")
    else:
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    return target.as_uri(), checksum


def _markdown(payload: dict) -> str:
    summary = payload["summary"]
    rows = [
        "# 少数品目データ受入 技術判定レポート",
        "",
        f"- case ID: `{payload['case_id']}`",
        f"- 判定: **{payload['outcome']}**",
        f"- データ区分: `{payload['definition']['data_kind']}`",
        f"- 日次build: `{payload['definition']['daily_build_id']}`",
        f"- 品目数: {summary.get('product_count', 0)}",
        f"- 系列数: {summary.get('series_count', 0)}",
        f"- 行数: {summary.get('row_count', 0)}",
        "",
        "## 技術チェック",
        "",
        "| ID | 結果 | 内容 |",
        "|---|---|---|",
    ]
    rows.extend(
        f"| {item['check_id']} | {item['status']} | {item['detail']} |"
        for item in payload["checks"]
    )
    rows.extend(["", "## 制約", ""])
    rows.extend(f"- {value}" for value in summary.get("limitations", []))
    return "\n".join(rows) + "\n"
