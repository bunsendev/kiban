"""v2.8で再現した比較集合の縮小と将来変数の時点漏洩を検証する。"""

import pandas as pd
import pytest
from test_v26_regressions import fixture_comparison

from forecast_provider.errors import ContractViolationError
from forecast_provider.evaluation import compare_runs
from forecast_provider.features import attach_features
from forecast_provider.runner import available_history


def test_own_metrics_do_not_change_when_failed_schedule_is_added():
    sparse, daily, sparse_out, daily_out, truth = fixture_comparison()
    daily_out.loc[
        daily_out.origin_date.eq(pd.Timestamp("2026-01-01")) & daily_out.horizon.eq(7),
        ["yhat_raw", "yhat"],
    ] = 100.0
    alone = compare_runs({"a": daily}, {"a": daily_out}, truth, truth_version="v1", horizon=7)
    mixed = compare_runs(
        {"a": daily, "bad": sparse},
        {"a": daily_out, "bad": sparse_out.iloc[:0]},
        truth,
        truth_version="v1",
        horizon=7,
    )
    assert alone["scores"]["a"]["own_metrics"]["wape_pct"] == pytest.approx(900 / 14)
    assert alone["scores"]["a"]["own_metrics"] == mixed["scores"]["a"]["own_metrics"]
    assert mixed["scores"]["a"]["own_success_count"] == 14
    assert mixed["scores"]["a"]["shared_planned_count"] == 2


def test_official_population_and_id_ignore_incomplete_schedule():
    sparse, daily, sparse_out, daily_out, truth = fixture_comparison()
    base = compare_runs(
        {"a": daily, "b": daily},
        {"a": daily_out, "b": daily_out},
        truth,
        truth_version="v1",
        horizon=7,
    )
    mixed = compare_runs(
        {"a": daily, "b": daily, "bad": sparse},
        {"a": daily_out, "b": daily_out, "bad": sparse_out.iloc[:0]},
        truth,
        truth_version="v1",
        horizon=7,
    )
    assert mixed["scores"]["a"]["official_common_success_count"] == 14
    assert mixed["official_comparison_set_id"] == base["official_comparison_set_id"]
    assert mixed["official_ranking_ready"]
    assert not mixed["ranking_ready"]


def test_official_id_changes_with_candidates_even_if_all_common_empty():
    _, daily, _, out, truth = fixture_comparison()
    ds = {"a": daily, "b": daily, "c": daily}
    two = compare_runs(
        ds, {"a": out, "b": out, "c": out.iloc[:0]}, truth, truth_version="v1", horizon=7
    )
    one = compare_runs(
        ds, {"a": out, "b": out.iloc[:0], "c": out.iloc[:0]}, truth, truth_version="v1", horizon=7
    )
    assert two["official_comparison_set_id"] != one["official_comparison_set_id"]
    assert one["official_evaluation_ready"]
    assert not one["official_ranking_ready"]


def test_no_valid_truth_cannot_create_official_ranking():
    a, _, out, _, truth = fixture_comparison()
    truth["y"] = float("nan")
    report = compare_runs({"a": a, "b": a}, {"a": out, "b": out}, truth, truth_version="v1")
    assert report["official_runs"] == []
    assert not report["official_evaluation_ready"]
    assert report["scores"]["a"]["own_metrics"]["wape_pct"] is None


def targets():
    return pd.DataFrame(
        {
            "unique_id": ["A", "A"],
            "origin_date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "target_date": pd.to_datetime(["2026-01-03", "2026-01-03"]),
            "horizon": [2, 1],
        }
    )


def versions():
    return pd.DataFrame(
        {
            "unique_id": ["A", "A", "A"],
            "ds": pd.to_datetime(["2026-01-03"] * 3),
            "feature": ["promo"] * 3,
            "value": [10.0, 20.0, 999.0],
            "known_at": pd.to_datetime(
                ["2026-01-01T12:00+09:00", "2026-01-02T12:00+09:00", "2027-01-01T00:00+09:00"]
            ),
        }
    )


def test_known_future_selects_version_per_origin_and_ignores_later_revision():
    source = versions()
    out = attach_features(targets(), ("promo",), versions=source)
    assert out.promo.tolist() == [10.0, 20.0]
    source.loc[2, "value"] = 12345.0
    assert attach_features(targets(), ("promo",), versions=source).promo.tolist() == [10.0, 20.0]
    source.loc[0, "known_at"] = pd.Timestamp("2026-01-02T00:00+09:00")
    assert attach_features(targets(), ("promo",), versions=source).promo.iloc[0] == 10.0


def test_unknown_at_origin_is_rejected_not_taken_from_final_data():
    with pytest.raises(ContractViolationError):
        attach_features(targets(), ("promo",))
    with pytest.raises(ContractViolationError):
        attach_features(targets(), ("promo",), versions=versions().iloc[2:])


def test_invalid_feature_versions_rejected():
    source = versions()
    with pytest.raises(ContractViolationError):
        attach_features(targets(), ("promo",), versions=pd.concat([source, source.iloc[:1]]))
    source["known_at"] = source.known_at.dt.tz_localize(None)
    with pytest.raises(ContractViolationError):
        attach_features(targets(), ("promo",), versions=source)


def test_calendar_is_generated_not_read_from_final_values():
    out = attach_features(targets(), ("calendar_dayofweek", "calendar_month"))
    assert out.calendar_dayofweek.tolist() == [5, 5]
    assert out.calendar_month.tolist() == [1, 1]
    hist = pd.DataFrame({"unique_id": ["A"], "ds": pd.to_datetime(["2026-01-03"]), "y": [1.0]})
    out = available_history(
        hist,
        pd.Timestamp("2026-01-03"),
        availability_mode="ASSUMED",
        known_future_columns=("calendar_month",),
    )
    assert out.calendar_month.tolist() == [1]


def test_two_complete_different_schedules_use_only_their_shared_keys():
    a, b, oa, ob, truth = fixture_comparison()
    r = compare_runs({"a": a, "b": b}, {"a": oa, "b": ob}, truth, truth_version="v1", horizon=7)
    assert r["official_planned_count"] == 2
    assert r["scores"]["b"]["own_success_count"] == 14
    reverse = compare_runs(
        {"b": b, "a": a}, {"b": ob, "a": oa}, truth, truth_version="v1", horizon=7
    )
    assert reverse["official_comparison_set_id"] == r["official_comparison_set_id"]
