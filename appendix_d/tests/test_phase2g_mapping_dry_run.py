"""Phase 2G クレンジング・列mappingドライラン。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from forecast_provider.mapping_dry_run import DryRunLimits, cli
from forecast_provider.mapping_dry_run.inspector import inspect_sample
from forecast_provider.mapping_dry_run.loader import load_mapping, load_source
from forecast_provider.mapping_dry_run.report import publish_report
from forecast_provider.mapping_dry_run.runner import collect_dry_run


def _mapping() -> dict:
    return {
        "date_column": "出荷日",
        "jan_column": "JANコード",
        "product_name_column": "商品名称",
        "quantity_column": "出荷数量",
        "unit_column": "数量単位",
        "center_column": "物流拠点",
        "row_type_column": "明細種別",
        "date_formats": ["%Y/%m/%d"],
        "allowed_units": ["個"],
        "availability_mode": "ASSUMED",
        "file_mode": "FULL",
    }


def _write_inputs(tmp_path, rows: list[str], mapping=None):
    input_root = tmp_path / "input"
    input_root.mkdir()
    source = input_root / "shipment-secret.csv"
    header = "出荷日,JANコード,商品名称,出荷数量,数量単位,物流拠点,明細種別\n"
    source.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(
        json.dumps(_mapping() if mapping is None else mapping, ensure_ascii=False),
        encoding="utf-8",
    )
    return input_root, mapping_file


def _collect(tmp_path, rows, *, mapping=None, limits=None):
    input_root, mapping_file = _write_inputs(tmp_path, rows, mapping)
    report = collect_dry_run(
        input_root,
        "shipment-secret.csv",
        mapping_file,
        limits or DryRunLimits(),
        now=lambda: datetime(2026, 9, 13, tzinfo=UTC),
    )
    return report, input_root, mapping_file


def test_valid_sample_is_ready_and_report_has_no_raw_values(tmp_path):
    rows = [
        "2026/09/01,0012345678901,秘密商品A,999999,個,非公開拠点,SHIPMENT",
        "2026/09/02,0012345678902,秘密商品B,1,個,非公開拠点,SHIPMENT",
    ]
    report, _, _ = _collect(tmp_path, rows)
    assert report["outcome"] == "READY_FOR_NORMALIZATION"
    assert len(report["checks"]) == 9
    assert all(item["status"] == "PASSED" for item in report["checks"])
    assert report["observations"] == {
        "sampled_rows": 2,
        "accepted_rows": 2,
        "quarantined_rows": 0,
        "truncated": False,
        "quarantine_reason_counts": {},
    }
    encoded = json.dumps(report, ensure_ascii=False)
    for secret in (
        "shipment-secret",
        "出荷日",
        "0012345678901",
        "秘密商品A",
        "999999",
        "非公開拠点",
    ):
        assert secret not in encoded


def test_invalid_rows_require_review_with_reason_codes_only(tmp_path):
    rows = [
        "bad-date,,秘密商品A,-5,箱,非公開拠点,RETURN",
        "2026/09/02,0012345678902,秘密商品B,1,個,非公開拠点,SHIPMENT",
    ]
    report, _, _ = _collect(tmp_path, rows)
    assert report["outcome"] == "REVIEW_REQUIRED"
    assert report["observations"]["accepted_rows"] == 1
    assert report["observations"]["quarantined_rows"] == 1
    assert report["observations"]["quarantine_reason_counts"] == {
        "INVALID_DATE": 1,
        "MISSING_JAN": 1,
        "NEGATIVE_QUANTITY": 1,
        "NON_SHIPMENT_ROW": 1,
        "UNIT_NOT_ALLOWED": 1,
    }
    assert "秘密商品A" not in json.dumps(report, ensure_ascii=False)


def test_sample_limit_is_explicit_and_does_not_read_result_rows_beyond_limit(tmp_path):
    rows = [
        "2026/09/01,001,商品A,1,個,拠点,SHIPMENT",
        "2026/09/02,002,商品B,2,個,拠点,SHIPMENT",
    ]
    report, _, _ = _collect(tmp_path, rows, limits=DryRunLimits(sample_rows=1))
    assert report["outcome"] == "READY_FOR_NORMALIZATION"
    assert report["observations"]["sampled_rows"] == 1
    assert report["observations"]["truncated"] is True


def test_inspection_uses_the_same_bytes_that_were_hashed(tmp_path):
    input_root, mapping_file = _write_inputs(
        tmp_path,
        ["2026/09/01,001,商品A,1,個,拠点,SHIPMENT"],
    )
    source = load_source(input_root, "shipment-secret.csv", DryRunLimits())
    mapping = load_mapping(mapping_file, DryRunLimits())
    (input_root / "shipment-secret.csv").write_text("差し替え後の内容", encoding="utf-8")

    inspection = inspect_sample(source, mapping.definition, 1_000)

    assert inspection.accepted_rows == 1
    assert inspection.quarantined_rows == 0


@pytest.mark.parametrize(
    ("mapping_change", "expected_check"),
    [
        ({"quantity_column": "存在しない列"}, "REQUIRED_COLUMNS"),
        ({"availability_mode": "OBSERVED"}, "MAPPING_CONTRACT"),
    ],
)
def test_mapping_contract_or_missing_column_blocks(tmp_path, mapping_change, expected_check):
    mapping = _mapping()
    mapping.update(mapping_change)
    report, _, _ = _collect(
        tmp_path,
        ["2026/09/01,001,商品,1,個,拠点,SHIPMENT"],
        mapping=mapping,
    )
    assert report["outcome"] == "BLOCKED"
    assert report["checks"][-1]["check_id"] == expected_check
    assert report["checks"][-1]["status"] == "FAILED"


def test_duplicate_header_and_empty_file_block(tmp_path):
    input_root, mapping_file = _write_inputs(
        tmp_path,
        ["2026/09/01,001,商品,1,個,拠点,SHIPMENT"],
    )
    source = input_root / "shipment-secret.csv"
    source.write_text(
        "出荷日,JANコード,商品名称,出荷数量,数量単位,物流拠点,物流拠点\n"
        "2026/09/01,001,商品,1,個,拠点,SHIPMENT\n",
        encoding="utf-8",
    )
    duplicate = collect_dry_run(input_root, source.name, mapping_file)
    assert duplicate["outcome"] == "BLOCKED"
    assert duplicate["checks"][-1]["check_id"] == "HEADER_UNIQUE"
    source.write_text(
        "出荷日,JANコード,商品名称,出荷数量,数量単位,物流拠点,明細種別\n",
        encoding="utf-8",
    )
    empty = collect_dry_run(input_root, source.name, mapping_file)
    assert empty["checks"][-1]["check_id"] == "SAMPLE_ROWS"


def test_path_escape_symlink_and_size_limit_block(tmp_path):
    report, input_root, mapping_file = _collect(
        tmp_path,
        ["2026/09/01,001,商品,1,個,拠点,SHIPMENT"],
    )
    assert report["outcome"] == "READY_FOR_NORMALIZATION"
    escaped = collect_dry_run(input_root, "../mapping.json", mapping_file)
    assert escaped["checks"][-1]["check_id"] == "SOURCE_PATH_SAFE"
    link = input_root / "link.csv"
    try:
        link.symlink_to(input_root / "shipment-secret.csv")
    except OSError:
        pass
    else:
        linked = collect_dry_run(input_root, link.name, mapping_file)
        assert linked["checks"][-1]["check_id"] == "SOURCE_PATH_SAFE"
    oversized = collect_dry_run(
        input_root,
        "shipment-secret.csv",
        mapping_file,
        DryRunLimits(max_source_bytes=1_024),
    )
    if (input_root / "shipment-secret.csv").stat().st_size <= 1_024:
        (input_root / "shipment-secret.csv").write_bytes(b"a" * 1_025)
        oversized = collect_dry_run(
            input_root,
            "shipment-secret.csv",
            mapping_file,
            DryRunLimits(max_source_bytes=1_024),
        )
    assert oversized["checks"][-1]["check_id"] == "SOURCE_SIZE_LIMIT"


def test_unsupported_encoding_and_malformed_mapping_are_sanitized(tmp_path):
    report, input_root, mapping_file = _collect(
        tmp_path,
        ["2026/09/01,001,商品,1,個,拠点,SHIPMENT"],
    )
    assert report["outcome"] == "READY_FOR_NORMALIZATION"
    (input_root / "shipment-secret.csv").write_bytes(b"\x81")
    encoding = collect_dry_run(input_root, "shipment-secret.csv", mapping_file)
    assert encoding["checks"][-1]["check_id"] == "SOURCE_ENCODING"
    mapping_file.write_text("{broken", encoding="utf-8")
    malformed = collect_dry_run(input_root, "shipment-secret.csv", mapping_file)
    assert malformed["checks"] == [
        {"check_id": "MAPPING_CONTRACT", "status": "FAILED", "actual": False, "expected": True}
    ]


def test_report_is_content_addressed_and_cli_uses_exit_two_for_review(
    tmp_path, monkeypatch, capsys
):
    report, input_root, mapping_file = _collect(
        tmp_path,
        ["bad-date,001,商品,1,個,拠点,SHIPMENT"],
    )
    uri, checksum = publish_report(report, tmp_path / "output")
    target = next((tmp_path / "output" / "mapping-dry-run").iterdir())
    assert uri == target.as_uri()
    assert target.name == f"{checksum}.json"
    monkeypatch.setattr(
        cli,
        "run_dry_run",
        lambda *args: {
            "dry_run_id": "a" * 64,
            "outcome": "REVIEW_REQUIRED",
            "report_uri": uri,
            "report_sha256": checksum,
        },
    )
    code = cli.main(
        [
            "--input-root",
            str(input_root),
            "--source",
            "shipment-secret.csv",
            "--mapping-file",
            str(mapping_file),
            "--output-root",
            str(tmp_path / "output"),
        ]
    )
    assert code == 2
    assert '"outcome": "REVIEW_REQUIRED"' in capsys.readouterr().out
