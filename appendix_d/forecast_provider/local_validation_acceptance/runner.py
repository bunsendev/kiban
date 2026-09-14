"""healthから検証証跡までを一続きで判定する受入runner。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from .client import AcceptanceClient

EXPECTED_CHECKS = {
    "MAPPING_CONTRACT",
    "SOURCE_PATH_SAFE",
    "SOURCE_SIZE_LIMIT",
    "SOURCE_ENCODING",
    "HEADER_UNIQUE",
    "REQUIRED_COLUMNS",
    "SAMPLE_ROWS",
    "SAMPLE_ACCEPTANCE",
    "QUANTITY_RECONCILIATION",
}
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED"}


class AcceptanceError(RuntimeError):
    """実動受入条件を満たさない。"""


@dataclass(frozen=True)
class AcceptanceResult:
    outcome: str
    job_id: str
    report_sha256: str
    check_count: int
    sampled_rows: int
    accepted_rows: int
    quarantined_rows: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def run_acceptance(
    client: AcceptanceClient,
    *,
    source_path: str,
    mapping_id: str,
    sample_rows: int = 1000,
    wait_seconds: float = 30.0,
    poll_seconds: float = 0.5,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> AcceptanceResult:
    _require(client.get("/health").get("status") == "ok", "livenessが正常ではありません")
    readiness = client.get("/ready")
    _require(readiness.get("status") == "ready", "readinessが正常ではありません")

    sources = client.get("/api/mapping-dry-run-sources")
    _require(sources.get("configured") is True, "入力rootが設定されていません")
    _require(
        any(item.get("source_path") == source_path for item in sources.get("items", [])),
        "指定CSVが安全な候補一覧にありません",
    )
    mappings = client.get("/api/mappings")
    _require(
        any(item.get("mapping_id") == mapping_id for item in mappings),
        "指定mappingがありません",
    )

    created = client.post(
        "/api/mapping-dry-run-jobs",
        {"source_path": source_path, "mapping_id": mapping_id, "sample_rows": sample_rows},
    )
    job_id = created.get("id") or created.get("job_id")
    _require(isinstance(job_id, str) and job_id, "job IDを取得できません")
    job = _wait_for_job(
        client,
        job_id,
        wait_seconds=wait_seconds,
        poll_seconds=poll_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    _require(job.get("status") == "SUCCEEDED", f"検証jobが失敗しました: {job.get('error_code')}")
    report_sha256 = job.get("report_sha256")
    _require(isinstance(report_sha256, str) and report_sha256, "証跡SHA-256がありません")
    report = client.report(report_sha256)
    _require(report.get("outcome") == "READY_FOR_NORMALIZATION", "正規化準備完了ではありません")
    checks = report.get("checks", [])
    passed = {item.get("check_id") for item in checks if item.get("status") == "PASSED"}
    _require(
        passed == EXPECTED_CHECKS and len(checks) == len(EXPECTED_CHECKS),
        "9検査が全件合格ではありません",
    )
    observations = report.get("observations", {})
    return AcceptanceResult(
        outcome=report["outcome"],
        job_id=job_id,
        report_sha256=report_sha256,
        check_count=len(checks),
        sampled_rows=int(observations.get("sampled_rows", 0)),
        accepted_rows=int(observations.get("accepted_rows", 0)),
        quarantined_rows=int(observations.get("quarantined_rows", 0)),
    )


def _wait_for_job(
    client: AcceptanceClient,
    job_id: str,
    *,
    wait_seconds: float,
    poll_seconds: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    deadline = monotonic() + wait_seconds
    while True:
        job = client.job(job_id)
        if job.get("status") in TERMINAL_STATUSES:
            return job
        if monotonic() >= deadline:
            raise AcceptanceError("検証jobが制限時間内に完了しませんでした")
        sleep(poll_seconds)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)
