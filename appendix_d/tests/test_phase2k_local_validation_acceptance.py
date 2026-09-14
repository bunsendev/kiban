"""Phase 2K: ローカル検証環境の実動受入。"""

from pathlib import Path

from forecast_provider.local_validation_acceptance import AcceptanceError, run_acceptance
from forecast_provider.local_validation_acceptance.client import _safe_base_url


class FakeClient:
    def __init__(self, jobs=None):
        self.jobs = iter(jobs or [{"status": "SUCCEEDED", "report_sha256": "a" * 64}])

    def get(self, path):
        responses = {
            "/health": {"status": "ok"},
            "/ready": {"status": "ready"},
            "/api/mapping-dry-run-sources": {
                "configured": True,
                "items": [{"source_path": "sample.csv"}],
            },
            "/api/mappings": [{"mapping_id": "map-1"}],
        }
        return responses[path]

    def post(self, path, payload):
        assert path == "/api/mapping-dry-run-jobs"
        assert payload["source_path"] == "sample.csv"
        return {"id": "job-1"}

    def job(self, job_id):
        assert job_id == "job-1"
        return next(self.jobs)

    def report(self, report_sha256):
        from forecast_provider.local_validation_acceptance.runner import EXPECTED_CHECKS

        return {
            "outcome": "READY_FOR_NORMALIZATION",
            "checks": [{"check_id": check, "status": "PASSED"} for check in EXPECTED_CHECKS],
            "observations": {"sampled_rows": 2, "accepted_rows": 2, "quarantined_rows": 0},
        }


def test_acceptance_runs_health_job_and_nine_report_checks():
    result = run_acceptance(
        FakeClient([{"status": "RUNNING"}, {"status": "SUCCEEDED", "report_sha256": "a" * 64}]),
        source_path="sample.csv",
        mapping_id="map-1",
        sleep=lambda _: None,
    )
    assert result.outcome == "READY_FOR_NORMALIZATION"
    assert result.check_count == 9
    assert result.accepted_rows == 2


def test_acceptance_rejects_non_ready_environment():
    client = FakeClient()
    original = client.get
    client.get = lambda path: {"status": "not-ready"} if path == "/ready" else original(path)
    try:
        run_acceptance(client, source_path="sample.csv", mapping_id="map-1")
    except AcceptanceError as exc:
        assert "readiness" in str(exc)
    else:
        raise AssertionError("AcceptanceErrorが必要です")


def test_plain_http_is_limited_to_loopback():
    assert _safe_base_url("http://127.0.0.1:58000/") == "http://127.0.0.1:58000"
    try:
        _safe_base_url("http://example.test")
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("ValueErrorが必要です")


def test_wizard_handles_job_that_finishes_before_first_poll():
    app = Path(__file__).parents[1] / "forecast_provider/ui/static/intake_app.js"
    script = app.read_text(encoding="utf-8")
    assert "if (!await openCompletedDryRunReport(state.detail))" in script
    assert "await openCompletedDryRunReport(job);" in script
