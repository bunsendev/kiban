"""実データ受入プリフライトの境界、秘匿、保存を検証する。"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from forecast_provider.real_data_preflight import PreflightRoots
from forecast_provider.real_data_preflight import cli as preflight_cli
from forecast_provider.real_data_preflight.contracts import REQUIRED_RELATIONS
from forecast_provider.real_data_preflight.database import inspect_database
from forecast_provider.real_data_preflight.filesystem import inspect_filesystem, probe_writable
from forecast_provider.real_data_preflight.report import publish_report
from forecast_provider.real_data_preflight.runner import collect_preflight


def roots_outside(tmp_path: Path) -> tuple[PreflightRoots, Path]:
    application = tmp_path / "application"
    application.mkdir()
    values = {}
    for name in ("import", "archive", "snapshot", "acceptance", "preflight"):
        path = tmp_path / "private" / name
        path.mkdir(parents=True)
        values[name] = path
    return (
        PreflightRoots(
            import_root=values["import"],
            archive_root=values["archive"],
            snapshot_root=values["snapshot"],
            acceptance_root=values["acceptance"],
            report_root=values["preflight"],
        ),
        application,
    )


def ready_database() -> dict:
    return {
        "reachable": True,
        "server_major": 17,
        "required_relation_count": len(REQUIRED_RELATIONS),
        "present_relation_count": len(REQUIRED_RELATIONS),
        "missing_relations": [],
        "insufficient_privileges": [],
    }


def test_contract_requires_absolute_roots(tmp_path: Path) -> None:
    roots, application = roots_outside(tmp_path)
    invalid = PreflightRoots(
        import_root=Path("relative"),
        archive_root=roots.archive_root,
        snapshot_root=roots.snapshot_root,
        acceptance_root=roots.acceptance_root,
        report_root=roots.report_root,
    )
    with pytest.raises(ValueError, match="絶対path"):
        invalid.validate(application)


def test_filesystem_inspection_enforces_access_and_separation(tmp_path: Path) -> None:
    roots, application = roots_outside(tmp_path)
    observed = inspect_filesystem(
        roots.requirements(),
        application,
        writable_probe=lambda path: path != roots.import_root,
    )
    assert all(item["exists"] and item["directory"] and item["readable"] for item in observed)
    assert all(not item["contains_symlink"] and not item["overlaps"] for item in observed)
    assert all(item["outside_application_root"] for item in observed)
    assert all(item["writable"] == item["expected_writable"] for item in observed)


def test_filesystem_inspection_detects_overlapping_roots(tmp_path: Path) -> None:
    roots, application = roots_outside(tmp_path)
    nested = roots.archive_root / "nested"
    nested.mkdir()
    overlapping = PreflightRoots(
        import_root=roots.import_root,
        archive_root=roots.archive_root,
        snapshot_root=nested,
        acceptance_root=roots.acceptance_root,
        report_root=roots.report_root,
    )
    observed = inspect_filesystem(
        overlapping.requirements(), application, writable_probe=lambda _: True
    )
    by_id = {item["root_id"]: item for item in observed}
    assert by_id["raw_archive"]["overlaps"] == ["snapshot"]
    assert by_id["snapshot"]["overlaps"] == ["raw_archive"]


def test_write_probe_handles_read_only_mount_without_cleanup_error(
    monkeypatch, tmp_path: Path
) -> None:
    def reject(*_):
        raise OSError("read-only")

    monkeypatch.setattr(os, "open", reject)
    assert probe_writable(tmp_path) is False


class FakeCursor:
    def __init__(self) -> None:
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=None) -> None:
        if "server_version_num" in query:
            self.result = (170_005,)
        elif "information_schema.tables" in query:
            self.result = [(name,) for name in REQUIRED_RELATIONS]
        else:
            self.result = (True,)

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self) -> FakeCursor:
        return FakeCursor()


def test_database_check_reports_only_required_technical_evidence() -> None:
    result = inspect_database("postgresql://secret@private/db", connect=lambda *_: FakeConnection())
    assert result == ready_database()
    assert "secret" not in json.dumps(result)


def test_database_failure_does_not_copy_connection_message() -> None:
    def reject(dsn: str):
        raise RuntimeError(f"connection failed for {dsn}")

    result = inspect_database("postgresql://user:very-secret@private/db", connect=reject)
    serialized = json.dumps(result)
    assert result["reachable"] is False
    assert result["failure_class"] == "RuntimeError"
    assert "very-secret" not in serialized and "private" not in serialized


def test_collect_is_ready_and_excludes_paths_dsn_and_filenames(tmp_path: Path) -> None:
    roots, application = roots_outside(tmp_path)
    filesystem = inspect_filesystem(
        roots.requirements(),
        application,
        writable_probe=lambda path: path != roots.import_root,
    )
    report = collect_preflight(
        roots,
        application,
        "postgresql://user:top-secret@database/kiban",
        filesystem_reader=lambda *_: filesystem,
        database_reader=lambda _: ready_database(),
        now=lambda: datetime(2026, 9, 13, tzinfo=UTC),
    )
    assert report["outcome"] == "READY_FOR_DATA"
    assert len(report["checks"]) == 10
    assert all(item["status"] == "PASSED" for item in report["checks"])
    serialized = json.dumps(report, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "top-secret" not in serialized
    assert "source.csv" not in serialized


def test_report_is_content_addressed_and_immutable(tmp_path: Path) -> None:
    payload = {"outcome": "READY_FOR_DATA", "checks": []}
    first = publish_report(payload, tmp_path)
    second = publish_report(payload, tmp_path)
    assert first == second
    target = tmp_path / "real-data-preflight" / f"{first[1]}.json"
    assert target.read_text(encoding="utf-8").endswith("\n")


@pytest.mark.parametrize(
    ("outcome", "expected"), (("READY_FOR_DATA", 0), ("BLOCKED", 2))
)
def test_cli_returns_preflight_status(
    monkeypatch, tmp_path: Path, outcome: str, expected: int
) -> None:
    roots = [tmp_path / name for name in ("app", "in", "archive", "snap", "accept", "out")]
    for path in roots:
        path.mkdir()
    monkeypatch.setattr(
        preflight_cli,
        "run_preflight",
        lambda *_: {
            "preflight_id": "b" * 64,
            "outcome": outcome,
            "report_uri": "file:///report.json",
            "report_sha256": "a" * 64,
        },
    )
    argv = [
        "--postgres-dsn",
        "postgresql://unused",
        "--application-root",
        str(roots[0]),
        "--import-root",
        str(roots[1]),
        "--archive-root",
        str(roots[2]),
        "--snapshot-root",
        str(roots[3]),
        "--acceptance-root",
        str(roots[4]),
        "--output-root",
        str(roots[5]),
    ]
    assert preflight_cli.main(argv) == expected


@pytest.mark.skipif(not os.getenv("KIBAN_TEST_POSTGRES_DSN"), reason="PostgreSQL test DSNなし")
def test_live_postgres_has_real_data_pipeline_schema() -> None:
    result = inspect_database(os.environ["KIBAN_TEST_POSTGRES_DSN"])
    assert result == ready_database()
