import json
import time

import pytest
from fastapi.testclient import TestClient
from test_p1_flow import pilot_forecast_zip, synthetic_csv

from portable.api.app import create_app
from portable.api.forecast_batches import forecast_batches
from portable.api.input_csv import parse_csv


def test_batches_identical_checkpoint_resume_and_input_change(tmp_path, monkeypatch):
    import portable.api.forecast_batches as batches

    frame = parse_csv(synthetic_csv())
    original = batches.forecast
    expected = forecast_batches(frame, tmp_path, "all", batch_size=0)
    calls = []

    def failing(*args, **kwargs):
        calls.append(args[2])
        if len(calls) == 2:
            raise RuntimeError("simulated interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(batches, "forecast", failing)
    with pytest.raises(RuntimeError):
        forecast_batches(frame, tmp_path, "split", batch_size=1)
    result = forecast_batches(frame, tmp_path, "split", batch_size=1)
    assert result == expected
    assert len(calls) == 3  # completed first batch was reused
    frame.loc[frame["unique_id"] == "SYNTHETIC-001", "y"] += 1
    changed = forecast_batches(frame, tmp_path, "split", batch_size=1)
    assert changed != result
    assert len(calls) == 4  # unchanged second batch reused
    with pytest.raises(ValueError):
        forecast_batches(frame, tmp_path, "bad", batch_size=-1)


@pytest.mark.parametrize("count", [1, 201])
def test_all_products_pass_inventory_and_production(tmp_path, count):
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        report = client.post(
            "/api/business-archives",
            content=pilot_forecast_zip(count),
            headers={"Content-Type": "application/zip"},
        ).json()
        analysis = report["analysis_id"]
        handoff = client.post(
            f"/api/business-archives/{analysis}/formal-inventory",
            json={
                "actor": "検証",
                "reason": "全商品確認",
                "confirm_case": True,
                "locations": [
                    {
                        "source_center": "神戸",
                        "location_code": "KOBE",
                        "location_name": "神戸倉庫",
                        "snapshot_time": "16:00",
                    }
                ],
            },
        )
        assert handoff.status_code == 201, handoff.text
        if count == 201:
            handoff_id = handoff.json()["handoff_id"]
            endpoint = f"/api/formal-inventory/{handoff_id}/pipeline"
            scope = client.get(endpoint).json()
            registered = client.post(
                endpoint,
                json={
                    "actor": "以前の担当者",
                    "reason": "旧20商品制限",
                    "confirm_pilot_scope": True,
                    "selections": [
                        {"source_center": "神戸", "jans": scope["locations"][0]["jans"][:20]}
                    ],
                },
            )
            assert registered.status_code == 201, registered.text
            assert client.get(endpoint).json()["latest_covers_all"] is False
            assert client.get(f"/api/daily-runs/{analysis}").json()["status"] == "READY_TO_ADVANCE"
        response = client.post(
            f"/api/daily-runs/{analysis}/advance",
            json={
                "actor": "検証",
                "reason": "全商品確認",
                "batch_size": 25,
                "confirm_pilot_scope": True,
                "confirm_quantity_reconciliation": True,
                "confirm_identity_bridge": True,
                "confirm_zero_policy": True,
            },
        )
        assert response.status_code == 201, response.text
        value = response.json()
        assert value["eligible_series_count"] == count
        deadline = time.monotonic() + 30
        while value["status"] == "PRODUCTION_RUNNING" and time.monotonic() < deadline:
            time.sleep(0.05)
            value = client.get(f"/api/daily-runs/{analysis}").json()
        assert value["status"] == "SUMMARY_CONFIRMATION_REQUIRED", value
        result = client.get(f"/api/operator-results/production/{value['build_id']}").json()
        assert len(result["rows"]) == count * 14
        metrics = client.get(f"/api/performance/{analysis}").json()["stages"]
        assert metrics[0]["series_count"] == count
        assert metrics[0]["status"] == "SUCCEEDED"
        assert metrics[0]["elapsed_seconds"] > 0
        assert metrics[0]["peak_rss_mb"] is None or metrics[0]["peak_rss_mb"] > 0
        cached = list((tmp_path / "State" / "ForecastBatches").glob("*/performance.json"))
        assert sum(json.loads(p.read_text())["series_count"] for p in cached) == count
