from copy import deepcopy

import pytest

from portable.document_accuracy import FIELDS, evaluate


def dataset():
    values = dict.fromkeys(FIELDS, "")
    values.update(jan="4901234567894", case_quantity="10", loose_quantity="0")
    row = {
        "id": "original-row-1",
        "source_sha256": "a" * 64,
        "page": "1",
        "status": "HUMAN_CONFIRMED",
        "confirmed_by": "人工",
        "confirmed_values": values,
    }
    truth = {
        "pages": [
            {
                "source_sha256": "a" * 64,
                "page": "1",
                "all_rows_confirmed": True,
                "confirmed_by": "人工",
            }
        ],
        "records": [row],
    }
    predicted = {
        "id": row["id"],
        "source_sha256": row["source_sha256"],
        "page": "1",
        "predicted_values": deepcopy(values),
        "classification": "READY",
    }
    return truth, {"records": [predicted]}


def test_field_metrics_preserve_blank_zero_and_are_reproducible():
    truth, prediction = dataset()
    prediction["records"][0]["predicted_values"]["case_quantity"] = "10.00"
    result = evaluate(truth, prediction)
    assert result == evaluate(truth, prediction)
    assert result["complete_correct_rows"] == 1
    prediction["records"][0]["predicted_values"]["loose_quantity"] = ""
    result = evaluate(truth, prediction)
    assert result["fields"]["loose_quantity"]["correct"] == 0
    assert result["wrong_automatic_rate"] == 1


def test_missing_extra_and_duplicate_rows_are_not_silently_dropped():
    truth, prediction = dataset()
    prediction["records"][0]["id"] = "false-row"
    prediction["records"].append(deepcopy(prediction["records"][0]))
    result = evaluate(truth, prediction)
    assert result["missing_rows"] == result["extra_rows"] == 1
    assert result["duplicate_predictions"] == 1
    assert result["wrong_automatic_candidates"] == 2
    assert result["row_recall"] == 0


@pytest.mark.parametrize("change", ["candidate", "incomplete", "different-page"])
def test_unconfirmed_or_unmatched_truth_is_rejected(change):
    truth, prediction = dataset()
    if change == "candidate":
        truth["records"][0]["status"] = "PENDING_HUMAN_CONFIRMATION"
    elif change == "incomplete":
        truth["pages"][0]["all_rows_confirmed"] = False
    else:
        prediction["records"][0]["page"] = "2"
    with pytest.raises(ValueError):
        evaluate(truth, prediction)


def test_unreadable_gold_is_not_counted_as_correct_automatic():
    truth, prediction = dataset()
    truth["records"][0]["unreadable_fields"] = ["case_quantity"]
    result = evaluate(truth, prediction)
    assert result["unverifiable_automatic_candidates"] == 1
    assert result["wrong_automatic_rate"] is None
    assert result["complete_correct_rows"] == 0
    truth["pages"].append(
        {"source_sha256": "b" * 64, "page": "1", "all_rows_confirmed": True, "confirmed_by": "人工"}
    )
    prediction["records"][0]["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="対応が矛盾"):
        evaluate(truth, prediction)
