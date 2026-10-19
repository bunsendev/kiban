from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from portable.api.app import create_app
from portable.api.field_store import FieldStore
from portable.api.forecast_verification import ForecastVerification
from portable.api.result_feedback import ResultFeedback

META = {
    "created_at": "2026-10-01T00:00:00+00:00",
    "unit": "CASE",
    "scope": "formal-jan-warehouse",
    "train_start": "2026-09-01",
    "train_end": "2026-09-30",
    "model": "test",
}
ROWS = [
    {"unique_id": "jan@warehouse", "target_date": "2026-10-02", "yhat": 10},
    {"unique_id": "jan@warehouse", "target_date": "2026-10-03", "yhat": 0},
    {"unique_id": "missing", "target_date": "2026-10-03", "yhat": None},
]


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "portable.api.forecast_verification.now", lambda: datetime(2026, 10, 20, 0, tzinfo=UTC)
    )
    return ForecastVerification(tmp_path / "forecast-verification.sqlite3")


def actual(day, value, **kw):
    return {
        "unique_id": "jan@warehouse",
        "day": day,
        "unit": "CASE",
        "scope": "formal-jan-warehouse",
        "quantity": value,
    } | kw


def test_metrics_no_adjustment_leak_or_blank_zero(ledger):
    ledger.capture("run", ROWS, META)
    ledger.import_actuals("accepted", [actual("2026-10-02", 12), actual("2026-10-03", 0)], "tester")
    out = ledger.compare("run", feedback={("jan@warehouse", "2026-10-02"): 999})
    assert out["count"] == 2 and out["mean_error"] == 1 and out["mae"] == 1
    assert out["wape"] == pytest.approx(2 / 12 * 100)
    assert out["rows"][0]["error_rate_percent"] == 20
    assert out["rows"][1]["error_rate_percent"] is None
    assert out["rows"][0]["adjusted_quantity"] == 999
    assert out["excluded"] == {"PREDICTION_MISSING": 1}
    assert out["by_product"]["jan@warehouse"]["count"] == 2
    assert ledger.compare("run", "2026-10-03", "2026-10-03")["count"] == 1
    with pytest.raises(ValueError):
        ledger.import_actuals("bad", [actual("2026-10-02", "")], "t")


def test_immutable_rerun_and_conflicting_reimport(ledger):
    ledger.capture("first", ROWS, META)
    ledger.capture("first", ROWS, META)
    with pytest.raises(ValueError):
        ledger.capture("first", [ROWS[0] | {"yhat": 77}], META)
    ledger.capture("second", [ROWS[0] | {"yhat": 77}], META)
    ledger.import_actuals("one", [actual("2026-10-02", 12)], "t")
    ledger.import_actuals("same", [actual("2026-10-02", 12)], "t")
    assert ledger.compare("first")["count"] == 1
    ledger.import_actuals("different", [actual("2026-10-02", 13)], "t")
    out = ledger.compare("first")
    assert out["count"] == 0 and out["excluded"]["ACTUAL_CONFLICT"] == 1
    assert out["rows"][0]["original_quantity"] == 10


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"unit": None}, "IDENTITY_OR_UNIT_UNKNOWN"),
        ({"created_at": None}, "FORECAST_TIME_UNKNOWN"),
        ({"created_at": "2026-10-03T00:00:00+00:00"}, "RETROSPECTIVE_FORECAST"),
    ],
)
def test_excluded_history(ledger, change, expected):
    ledger.capture("x", [ROWS[0]], META | change)
    ledger.import_actuals("one", [actual("2026-10-02", 12)], "t")
    assert ledger.compare("x")["excluded"] == {expected: 1}
    assert ledger.compare("unknown")["reason"] == "FORECAST_HISTORY_MISSING"


def test_scope_mismatch_and_zero_denominator(ledger):
    ledger.capture("x", [ROWS[0]], META)
    ledger.import_actuals("other", [actual("2026-10-02", 0, unit="EACH")], "t")
    assert ledger.compare("x")["count"] == 0
    ledger.import_actuals("right", [actual("2026-10-02", 0)], "t")
    out = ledger.compare("x")
    assert out["mae"] == 10 and out["wape"] is None


def test_edit_policy_dates_and_confirmed_state(ledger):
    assert ledger.edit_state("2026-10-19", "CONFIRMED")["code"] == "PAST_CONFIRMED"
    assert ledger.edit_state("2026-10-19")["code"] == "PAST_UNCONFIRMED"
    assert ledger.edit_state("2026-10-20")["code"] == "CUTOFF_UNSET"
    assert ledger.edit_state("2026-10-21")["editable"]
    assert not ledger.edit_state("2026-10-21", "CONFIRMED")["editable"]
    ledger.set_policy("16:00", "admin", "closing time")
    assert ledger.edit_state("2026-10-20")["editable"]
    assert not ledger.edit_state("2026-10-20", at=datetime(2026, 10, 20, 7, tzinfo=UTC))["editable"]


PAY = {
    "unique_id": "jan@warehouse",
    "target_date": "2026-10-02",
    "quantity": 5,
    "actor": "tester",
    "reason": "special",
    "rating": "OK",
}


def test_daily_guard_and_admin_audit(ledger, tmp_path, monkeypatch):
    f = ResultFeedback(tmp_path / "feedback.sqlite3")
    with pytest.raises(ValueError):
        f.save("run", ROWS, PAY, None)
    first = f.save("run", ROWS, PAY, None, exceptional=True)
    assert first["before_quantity"] is None and first["exceptional"]
    with pytest.raises(ValueError):
        f.save("run", ROWS, PAY | {"quantity": None, "revision": first["revision"]}, None)
    memo = f.save("run", ROWS, PAY | {"revision": first["revision"], "comment": "memo"}, None)
    assert memo["quantity"] == 5
    future = [ROWS[0] | {"target_date": "2026-10-21"}]
    assert f.save("future", future, PAY | {"target_date": "2026-10-21"}, None)["quantity"] == 5
    assert ROWS[0]["yhat"] == 10


def test_period_guard_does_not_distribute(ledger, tmp_path):
    f = FieldStore(tmp_path / "field.sqlite3")
    row = {
        "item": "jan@warehouse",
        "forecast": 10,
        "period": ["2026-10-02", "2026-10-25"],
        "unit": "箱",
    }
    p = {"choice": "CHANGE", "quantity": 7, "actor": "t", "reason": "r"}
    with pytest.raises(ValueError):
        f.save("r", row, p)
    saved = f.save("r", row, p, exceptional=True)
    assert saved["original_quantity"] == 10 and saved["before_quantity"] is None
    with pytest.raises(ValueError):
        f.save("r", row, p | {"choice": "ACCEPT", "quantity": None, "revision": saved["revision"]})
    same = f.save("r", row, p | {"revision": saved["revision"], "comment": "memo"})
    assert same["quantity"] == 7 and same["before_quantity"] == 7


def test_routes_auth_no_quantity_or_admin_bypass(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as c:
        assert c.get("/forecast-verification").status_code == 200
        assert c.get("/api/forecast-verification").json()["sources"] == []
        assert (
            c.post(
                "/api/forecast-verification/policy",
                json={"cutoff": "16:00", "actor": "a", "reason": "r"},
            ).status_code
            == 403
        )
        monkeypatch.setattr("portable.api.verification_routes.authorized", lambda *args: True)
        assert (
            c.post(
                "/api/forecast-verification/policy",
                json={"cutoff": "16:00", "actor": "a", "reason": "r"},
            ).status_code
            == 200
        )
        assert c.get("/api/forecast-verification/compare?source=no&start=bad").status_code == 422
        assert c.get("/api/forecast-verification/compare?source=no").json()["count"] == 0


def test_api_past_guard_and_authenticated_exception(tmp_path, monkeypatch):
    monkeypatch.setattr("portable.api.app.forecast", lambda *args: ROWS[:1])
    app = create_app(tmp_path)
    content = "ds,unique_id,y\n" + "".join(f"2026-09-{n:02d},a,1\n" for n in range(1, 9))
    with TestClient(app, base_url="http://localhost") as c:
        created = c.post("/api/runs", content=content, headers={"Content-Type": "text/csv"})
        assert created.status_code == 201, created.text
        run = created.json()
        url = f"/api/operator-results/run/{run['run_id']}"
        before = c.get(f"/api/runs/{run['run_id']}").json()["result_sha256"]
        assert c.post(url + "/feedback", json=[]).status_code == 422
        assert c.post(url + "/feedback", json=PAY).status_code == 422
        assert (
            c.post(url + "/feedback", json=PAY | {"exceptional": True, "role": "admin"}).status_code
            == 403
        )
        monkeypatch.setattr("portable.api.result_feedback_routes.authorized", lambda *args: True)
        saved = c.post(url + "/feedback", json=PAY | {"exceptional": True})
        assert saved.status_code == 201, saved.text
        assert saved.json()["exceptional"] and saved.json()["before_quantity"] is None
        assert c.get(f"/api/runs/{run['run_id']}").json()["result_sha256"] == before
        assert c.get(url).json()["rows"][0]["feedback"]["quantity"] == 5
        assert not c.get(url).json()["rows"][0]["edit_state"]["editable"]
        assert len(c.get("/api/forecast-verification").json()["sources"]) == 1


def test_actual_import_does_not_populate_adjustments(ledger, tmp_path):
    ledger.capture("x", ROWS, META)
    ledger.import_actuals("accepted", [actual("2026-10-02", 0)], "importer")
    feedback = ResultFeedback(tmp_path / "feedback.sqlite3")
    assert feedback.history("x") == []
    assert ledger.compare("x")["rows"][0]["adjusted_quantity"] is None
    with pytest.raises(ValueError):
        ledger.import_actuals("future", [actual("2026-10-21", 4)], "importer")
