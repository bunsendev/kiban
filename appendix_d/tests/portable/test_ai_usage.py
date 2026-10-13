import io
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from forecast_provider.field_pilot.ai_request import CURRENT, observe, options, sent
from portable.api.app import create_app
from portable.api.document_ai import FIELDS, DocumentError, extract
from portable.runtime.ai_usage import DEFAULT, AiUsage, counts


def response(model="gpt-6.1-sol", **changes):
    return {
        "model": model,
        "status": "completed",
        "usage": {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 100},
            "output_tokens": 500,
            "output_tokens_details": {"reasoning_tokens": 100},
        },
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"complete": True, "rows": [dict.fromkeys(FIELDS, "")]}),
                    }
                ],
            }
        ],
        **changes,
    }


def test_settings_persist_and_reject_bad_values(tmp_path):
    meter = AiUsage(tmp_path)
    assert meter.settings() == DEFAULT
    meter.save({**DEFAULT, "model": "gpt-6-luna"})
    assert AiUsage(tmp_path).settings()["model"] == "gpt-6-luna"
    for change in (
        {"model": "unknown"},
        {"yen_per_usd": float("nan")},
        {"monthly_requests": 1.5},
        {"monthly_budget_yen": False},
    ):
        with pytest.raises(ValueError):
            meter.save({**DEFAULT, **change})


@pytest.mark.parametrize(
    "model,effort",
    [
        ("gpt-4.1-mini", None),
        ("gpt-6-luna", "none"),
        ("gpt-6.1-sol", "low"),
        ("gpt-6-astra", "low"),
    ],
)
def test_request_model_parameters_and_usage_capture(tmp_path, model, effort):
    meter = AiUsage(tmp_path)
    meter.save({**DEFAULT, "model": model})

    def opener(request, **kwargs):
        body = json.loads(request.data)
        assert body["model"] == model and body["store"] is False
        assert body["input"][0]["content"][1]["detail"] == "high"
        if effort is not None:
            assert body["reasoning"] == {"effort": effort} and "temperature" not in body
        else:
            assert body["temperature"] == 0
        return io.BytesIO(json.dumps(response(model)).encode())

    meter.invoke("document", lambda: extract(b"%PDF-synthetic", "SYNTHETIC-SECRET", opener=opener))
    assert meter.summary()["calls"] == 1 and meter.summary()["unknown_cost"] == 0
    assert CURRENT.get() is None
    assert b"SYNTHETIC-SECRET" not in meter.path.read_bytes()


def test_cache_write_and_reasoning_not_double_charged(tmp_path):
    meter = AiUsage(tmp_path)
    meter.save({**DEFAULT, "model": "gpt-6.1-sol"})
    meter.invoke("document", lambda: observe(response()))
    summary = meter.summary()
    assert summary["usd"] == pytest.approx((700 * 2 + 200 * 0.1 + 100 * 2.5 + 500 * 10) / 1e6)
    assert summary["groups"][0]["reasoning_tokens"] == 100
    assert summary["estimate_basis"] == "this_month_same_model_document_average"
    old = summary["usd"]
    meter.save({**DEFAULT, "model": "gpt-6-astra", "yen_per_usd": 200})
    assert meter.summary()["usd"] == old
    assert meter.summary()["yen"] == old * 200


def test_failed_response_is_accounted_and_missing_usage_unknown(tmp_path):
    meter = AiUsage(tmp_path)

    def fail():
        observe(response("gpt-4.1-mini", status="incomplete"))
        raise DocumentError("incomplete")

    with pytest.raises(DocumentError):
        meter.invoke("document", fail)

    def network_fail():
        sent()
        raise DocumentError("network failure")

    with pytest.raises(DocumentError):
        meter.invoke("document", network_fail)
    summary = meter.summary()
    assert summary["unknown_cost"] == 1 and summary["groups"][0]["failed"] == 2
    assert summary["usd"] > 0
    assert CURRENT.get() is None


def test_unknown_tier_large_context_and_invalid_usage(tmp_path):
    meter = AiUsage(tmp_path)
    for value in (
        response("gpt-4.1-mini", service_tier="priority"),
        response("gpt-4.1-mini", usage={"input_tokens": 120000, "output_tokens": 1}),
        response("gpt-4.1-mini", usage=None),
    ):
        meter.invoke("document", lambda value=value: observe(value))
    assert meter.summary()["unknown_cost"] == 3
    assert counts({"usage": []}) is None
    assert counts({"usage": {"input_tokens": True, "output_tokens": 1}}) is None


def test_month_rollover_and_assumed_cost(tmp_path):
    meter = AiUsage(tmp_path)
    setting = {**DEFAULT, "model": "gpt-6.1-sol"}
    meter.save(setting)
    summary = meter.summary(datetime(2026, 10, 13, tzinfo=ZoneInfo("Asia/Tokyo")))
    assert summary["planned_yen"] == pytest.approx(2232)
    assert summary["month_end_yen"] is None
    with meter.db() as db:
        db.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "2026-09-30T23:59:59+09:00",
                "gpt-4.1-mini",
                "document",
                "completed",
                1,
                "null",
                0.1,
                "2026-10-13",
                "{}",
            ),
        )
    assert meter.summary(datetime(2026, 10, 1, tzinfo=ZoneInfo("Asia/Tokyo")))["calls"] == 0
    assert meter.summary(datetime(2026, 9, 30, tzinfo=ZoneInfo("Asia/Tokyo")))["calls"] == 1


def test_settings_api_and_device_isolation(tmp_path):
    client = TestClient(create_app(tmp_path / "first"), base_url="http://127.0.0.1")
    second = TestClient(create_app(tmp_path / "second"), base_url="http://127.0.0.1")
    assert (
        client.post("/api/ai-settings", json={**DEFAULT, "model": "gpt-6-luna"}).status_code == 200
    )
    assert second.get("/api/ai-settings").json()["settings"]["model"] == "gpt-4.1-mini"
    assert client.post("/api/ai-settings", json={"model": "unknown"}).status_code == 422
    assert "api_key" not in client.get("/api/ai-settings").text


def test_context_model_does_not_leak_to_other_calls(tmp_path):
    meter = AiUsage(tmp_path)
    meter.save({**DEFAULT, "model": "gpt-6-luna"})
    assert meter.invoke("document", lambda: options("gpt-4.1-mini"))["model"] == "gpt-6-luna"
    assert options("gpt-4.1-mini")["model"] == "gpt-4.1-mini"
