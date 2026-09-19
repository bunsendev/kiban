"""Phase 3R: 追加テスト前後の事実差分と再レビュー引継ぎ。"""

import json
import sqlite3

from test_phase3q_review_retests import _payload, _review_fixture

from forecast_provider.model_review import (
    ReviewRetestSynchronizer,
    summarize_retest_comparison,
)


def test_summary_preserves_zero_missing_and_model_population_changes() -> None:
    source = _result(
        "source",
        [
            _model("p", "improved", wape=10.0, bias=-3.0, success=90.0, rank=2),
            _model("p", "zero", wape=0.0, bias=0.0, success=100.0, rank=1),
            _model("p", "removed", wape=5.0, bias=None, success=None, rank=3),
        ],
    )
    retest = _result(
        "retest",
        [
            _model("p", "improved", wape=8.0, bias=1.0, success=100.0, rank=1),
            _model("p", "zero", wape=1.0, bias=None, success=100.0, rank=2),
            _model("p", "added", wape=None, bias=0.0, success=0.0, rank=None),
        ],
    )

    summary = summarize_retest_comparison(
        source, retest, focus_provider_id="p", focus_model_id="improved"
    )
    models = {item["model_id"]: item for item in summary["models"]}

    assert summary["model_set_match"] is False
    assert summary["focus_model"]["direction"] == "IMPROVED"
    assert models["improved"]["wape_change_pct_points"] == -2.0
    assert models["improved"]["abs_bias_change_pct_points"] == -2.0
    assert models["zero"]["direction"] == "WORSENED"
    assert models["zero"]["wape_change_pct_points"] == 1.0
    assert models["zero"]["abs_bias_change_pct_points"] is None
    assert models["removed"]["direction"] == "NOT_COMPARABLE"
    assert models["added"]["source"] is None


def test_completed_retest_api_exposes_saved_official_deltas(tmp_path) -> None:
    api, database, snapshot_id, task, _actions, retests, campaigns = _review_fixture(
        tmp_path
    )
    source_campaign = api.get("/api/comparison-campaigns").json()[0]
    _set_scores(database, "phase3q-source-comparison", source_campaign["campaign_id"], [20, 10])
    started = api.post(
        f"/api/model-drift-review-actions/{task.action_id}/retests",
        json=_payload(snapshot_id),
    ).json()
    comparison_id = "phase3r-retest-comparison"
    _insert_empty_comparison(database, comparison_id)
    _set_scores(database, comparison_id, started["campaign_id"], [24, 8])
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE comparison_campaign_finalizations SET status='SUCCEEDED',"
            "finished_at='2026-09-19T12:00:00+00:00',comparison_id=? "
            "WHERE campaign_id=?",
            (comparison_id, started["campaign_id"]),
        )
    assert ReviewRetestSynchronizer(retests, campaigns).sync_pending() == 1

    response = api.get("/api/model-drift-review-retests")

    assert response.status_code == 200, response.text
    value = response.json()[0]
    summary = value["comparison_summary"]
    assert summary["availability"] == "READY"
    assert summary["basis"] == "official_common_metrics"
    assert summary["direction_counts"] == {
        "IMPROVED": 1,
        "WORSENED": 1,
        "UNCHANGED": 0,
        "NOT_COMPARABLE": 0,
    }
    assert summary["focus_model"]["model_id"] == "seasonal_naive_7"
    assert summary["focus_model"]["wape_change_pct_points"] == -2
    assert summary["focus_model"]["rank_change"] == 0


def _result(campaign_id: str, models: list[dict]) -> dict:
    return {
        "campaign_id": campaign_id,
        "comparison_id": f"comparison-{campaign_id}",
        "snapshot_id": f"snapshot-{campaign_id}",
        "selection_version": "selection-v1",
        "train_start": "2025-01-01",
        "train_end": "2025-01-31",
        "test_start": "2025-02-01",
        "test_end": "2025-02-07",
        "mode": "primary",
        "horizon": None,
        "models": models,
    }


def _model(provider, model, *, wape, bias, success, rank) -> dict:
    return {
        "provider_id": provider,
        "model_id": model,
        "official_eligible": wape is not None,
        "wape_pct": wape,
        "mae": wape,
        "rmse": wape,
        "bias_rate_pct": bias,
        "success_rate_pct": success,
        "rank": rank,
    }


def _set_scores(database, comparison_id: str, campaign_id: str, wapes: list[float]) -> None:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT run_id FROM comparison_campaign_entries "
            "WHERE campaign_id=? ORDER BY provider_id,model_id",
            (campaign_id,),
        ).fetchall()
        scores = {
            row[0]: {
                "official_eligible": True,
                "official_common_metrics": {
                    "wape_pct": wape,
                    "mae": wape / 2,
                    "rmse": wape / 1.5,
                    "bias_rate_pct": wape / 10,
                },
                "run_success_rate": 1.0,
            }
            for row, wape in zip(rows, wapes, strict=True)
        }
        connection.execute(
            "UPDATE comparison_reports SET result_json=? WHERE comparison_id=?",
            (json.dumps({"scores": scores}), comparison_id),
        )


def _insert_empty_comparison(database, comparison_id: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO comparison_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                comparison_id,
                1,
                f"phase3r-fingerprint-{comparison_id}",
                "{}",
                "{}",
                "set",
                "official",
                "truth",
                "scope",
                "primary",
                None,
                1,
                1,
                "2026-09-19T00:00:00+00:00",
            ),
        )
