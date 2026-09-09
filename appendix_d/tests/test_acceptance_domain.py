"""Phase 1K受入case契約の単体試験。"""

import pytest

from forecast_provider.acceptance import make_acceptance_case
from make_release import release_files


def payload():
    return {
        "acceptance_version": "v1",
        "daily_build_id": "daily-1",
        "data_kind": "ANONYMIZED",
        "expected_product_ids": ["p3", "p1", "p2"],
        "required_availability_mode": "ASSUMED",
        "min_usable_days_per_series": 30,
        "max_missing_rate": 0.05,
        "max_partial_invalid_rate": 0.01,
        "requested_by": "owner@example.test",
        "purpose": "受入手順確認",
    }


def test_case_is_content_addressed_and_product_order_independent():
    first = make_acceptance_case(payload())
    reordered = payload()
    reordered["expected_product_ids"] = ["p1", "p2", "p3"]
    assert make_acceptance_case(reordered) == first
    assert first.definition["expected_product_ids"] == ["p1", "p2", "p3"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("expected_product_ids", ["p1", "p2"], "3〜5件"),
        ("expected_product_ids", ["p1", "p2", "p2"], "重複のない"),
        ("max_missing_rate", 1.01, "0以上1以下"),
        ("min_usable_days_per_series", 0, "1以上"),
        ("data_kind", "UNKNOWN", "REALまたはANONYMIZED"),
    ],
)
def test_case_rejects_ambiguous_acceptance_scope(field, value, message):
    value_payload = payload()
    value_payload[field] = value
    with pytest.raises(ValueError, match=message):
        make_acceptance_case(value_payload)


def test_release_excludes_all_runtime_data_and_acceptance_reports():
    protected = {"snapshot_input", "import_input", "raw_archive", "acceptance_output"}
    assert all(protected.isdisjoint(path.parts) for path in release_files())
