import hashlib
import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from forecast_provider.providers.history_algorithms import (
    MODELS,
    predict_path,
    seasonal_signal,
    window_start,
)
from portable.api.app import create_app
from portable.api.candidate_packages import _run_smoke
from portable.api.forecast import forecast
from portable.api.formal_shipment_daily import build_daily_shipment
from portable.api.runtime_profiles import (
    BASELINE_CONFIGURATION,
    enforce_resource_limits,
    limits_for,
)
from portable.history_import import read_history_archive
from portable.history_study import CURRENT, METHODS, backtest, metrics, validate

JAN = "4901234567894"


def series_frame(days=1200):
    dates = pd.date_range("2022-01-01", periods=days)
    values = 100 + 20 * np.sin(np.arange(days) * 2 * np.pi / 365) + dates.dayofweek * 3
    return pd.DataFrame(
        {
            "unique_id": "SYNTH",
            "ds": dates,
            "y": values,
            "known_at": [d.isoformat() + "+09:00" for d in dates],
            "unit": "CASE",
        }
    )


def test_old_history_reaches_algorithm_and_future_is_ignored():
    dates = pd.date_range("2022-01-01", periods=1200)
    origin = dates[-1]
    target = origin + pd.Timedelta(days=1)
    history = pd.Series(1.0, index=dates)
    old = origin - pd.Timedelta(days=1000)
    changed = history.copy()
    changed.loc[old] = 10000
    for model in MODELS:
        a = predict_path(history, origin, [target], model)[0]
        b = predict_path(changed, origin, [target], model)[0]
        if model == "history_weekday_3y_v1":
            assert (
                b["yhat"] > a["yhat"]
                and b["used_start"] < str(origin - pd.Timedelta(days=365))[:10]
            )
        if model in {"history_weekday_28_v1", "history_weekday_365_v1"}:
            assert a["yhat"] == b["yhat"]
        future = history.copy()
        future.loc[target] = 1e9
        assert predict_path(future, origin, [target], model)[0]["yhat"] == a["yhat"]
    assert window_start("2024-02-29").date().isoformat() == "2021-03-01"


def test_seasonality_requires_repeatable_profiles():
    dates = pd.date_range("2022-01-01", "2024-12-31")
    flat = pd.Series(10.0, index=dates)
    assert not seasonal_signal(flat)["applied"]
    seasonal = pd.Series(20 + dates.month * 10, index=dates)
    assert seasonal_signal(seasonal)["applied"]
    result = predict_path(
        seasonal, dates[-1], [pd.Timestamp("2025-01-01")], "history_seasonal_recent_3y_v1"
    )[0]
    assert result["seasonality_applied"]
    fallback = predict_path(
        flat, dates[-1], [pd.Timestamp("2025-01-01")], "history_seasonal_recent_3y_v1"
    )[0]
    assert not fallback["seasonality_applied"] and fallback["yhat"] == 10


def test_common_targets_holdout_selection_and_no_future_leak():
    frame = series_frame()
    origins = list(pd.date_range("2024-01-10", periods=5, freq="28D"))
    first = backtest(frame, origins=origins, holdout_origins=1)
    assert set(first["summary"]["HOLDOUT"]) == set(METHODS)
    assert len({m["count"] for m in first["summary"]["HOLDOUT"].values()}) == 1
    edited = frame.copy()
    edited.loc[edited["ds"] > origins[-2] + pd.Timedelta(days=14), "y"] *= 100
    second = backtest(edited, origins=origins, holdout_origins=1)
    assert first["selections"][0]["selection_choice"] == second["selections"][0]["selection_choice"]
    a = [r["prediction"] for r in first["rows"] if r["origin"] == str(origins[0].date())]
    b = [r["prediction"] for r in second["rows"] if r["origin"] == str(origins[0].date())]
    assert a == b
    assert (
        first["frozen_product_selection_holdout"]["count"]
        == first["summary"]["HOLDOUT"][CURRENT]["count"]
    )
    assert metrics([{"actual": 0, "prediction": 0}])["wape"] is None


def test_quality_missing_zero_late_arrival_and_units():
    frame = series_frame(250)
    frame.loc[200, "y"] = np.nan
    frame.loc[201, "y"] = 0
    frame.loc[202, "known_at"] = "2050-01-01T00:00:00+09:00"
    result = backtest(
        frame, origin_count=5, holdout_origins=1, evaluation_at="2026-01-01T00:00:00Z"
    )
    assert result["quality"][0]["missing_days"] == 1 and result["quality"][0]["zero_days"] == 1
    for row in result["rows"]:
        if row["used_end"]:
            assert row["used_end"] <= row["origin"]
    with pytest.raises(ValueError):
        validate(pd.concat([frame, frame.iloc[:1]]))
    with pytest.raises(ValueError):
        validate(frame.assign(y=-1))
    mixed = frame.copy()
    mixed.loc[2, "unit"] = "EACH"
    with pytest.raises(ValueError):
        validate(mixed)
    unknown = frame.assign(unit="UNCONFIRMED")
    with pytest.raises(ValueError):
        backtest(unknown, origin_count=5, holdout_origins=1)
    conditional = backtest(unknown, origin_count=5, holdout_origins=1, allow_unconfirmed_units=True)
    assert conditional["settings"]["aggregation_status"] == "CONDITIONAL_UNCONFIRMED_UNITS"
    assert all(s["adoption_status"] == "KEEP_BASELINE" for s in conditional["selections"])


@pytest.mark.parametrize("model", list(MODELS))
def test_shared_provider_worker_smoke_and_limits(tmp_path, model):
    config = BASELINE_CONFIGURATION | {"version": "history-test", "model_name": model}
    assert _run_smoke(config, tmp_path)["forecast_count"] == 14
    max_days = 1096 if MODELS[model] is None else 400
    assert limits_for(config)["max_history_days"] == max_days
    enforce_resource_limits(config, series=2, history_days=max_days, horizon_days=14)
    with pytest.raises(ValueError):
        enforce_resource_limits(config, series=2, history_days=max_days + 1, horizon_days=14)
    with pytest.raises(ValueError):
        enforce_resource_limits(config, series=51, history_days=28, horizon_days=14)


def archive(content, name="history.csv"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(name, content)
    return out.getvalue()


def test_three_calendar_years_propagate_to_real_provider(tmp_path):
    dates = pd.date_range("2021-12-01", "2025-01-03")
    raw = archive("出荷日,JAN,数量,倉庫\n" + "".join(f"{d.date()},{JAN},1,TEST\n" for d in dates))
    src = tmp_path / "source.zip"
    src.write_bytes(raw)
    prepared = tmp_path / "prepared.csv"
    pd.DataFrame({"ds": dates.date.astype(str), "unique_id": "TEST:" + JAN, "y": 1}).to_csv(
        prepared, index=False
    )
    identity = {
        "source_center": "TEST",
        "jan": JAN,
        "canonical_product_id": JAN,
        "forecast_center_id": "TEST",
    }
    build, frame = build_daily_shipment(
        archive_path=src,
        prepared_path=prepared,
        handoff={"source_archive_sha256": hashlib.sha256(raw).hexdigest()},
        registration_id="synthetic",
        identities=[identity],
        zero_when_file_present=False,
        snapshot_dates_by_center={"TEST": dates[-1].date()},
    )
    assert build["train_start"] == "2022-01-04" and len(frame) == 1096
    assert build["history_policy_version"] == "three-calendar-years-v1"
    model = "history_weekday_3y_v1"
    direct = frame.set_index("ds")["y"]
    expected = predict_path(direct, dates[-1], [dates[-1] + pd.Timedelta(days=1)], model)[0]
    points = forecast(
        frame.drop(columns="source_center"), tmp_path, "history-provider", horizon=14, model=model
    )
    assert len(points) == 14 and points[0]["yhat"] == expected["yhat"] == 1


def test_import_quarantines_conflicts_and_preserves_explicit_zero():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "one.csv", f"出荷日,JAN,数量,倉庫\n2025-01-01,{JAN},0,TEST\n2025-01-02,{JAN},5,TEST\n"
        )
        z.writestr(
            "two.csv", f"出荷日,JAN,数量,倉庫\n2025-01-02,{JAN},7,TEST\n2025-01-03,{JAN},,TEST\n"
        )
    frame, meta = read_history_archive(out.getvalue())
    assert len(frame) == 1 and frame["y"].iloc[0] == "0"
    assert meta["counts"]["conflicted_product_dates"] == 1
    assert meta["counts"]["invalid_quantity_rows"] == 1
    assert not meta["formal_approval"]


def test_study_routes_preserve_operational_actuals_and_verify_hash(tmp_path):
    dates = pd.date_range("2024-01-01", periods=200)
    raw = archive("出荷日,JAN,数量,倉庫\n" + "".join(f"{d.date()},{JAN},10,TEST\n" for d in dates))
    app = create_app(tmp_path)
    from portable.api.forecast_verification import ForecastVerification

    ledger = ForecastVerification(tmp_path / "State" / "forecast-verification.sqlite3")
    ledger.capture("existing", [], {"test": True})
    with TestClient(app, base_url="http://localhost") as c:
        assert c.get("/history-studies").status_code == 200
        assert c.post("/api/history-studies/upload", content=raw).status_code == 422
        headers = {"x-history-availability-confirmed": "true", "x-history-unit": "CASE"}
        response = c.post("/api/history-studies/upload", content=raw, headers=headers)
        assert response.status_code == 201, response.text
        key = response.json()["study_id"]
        result = c.get("/api/history-studies/" + key).json()
        assert result["production_changed"] is False and result["row_count"] > 0
        assert len(result["rows"]) <= 100
        target = tmp_path / "State" / "HistoryStudies" / (key + ".json")
        value = json.loads(target.read_text("utf-8"))
        value["production_changed"] = True
        target.write_text(json.dumps(value), encoding="utf-8")
        assert c.get("/api/history-studies/" + key).status_code == 409
        assert app.state.active == 0
        with ledger.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM actual_values").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM forecast_versions").fetchone()[0] == 1
