"""Phase 2H mappingドライラン証跡の安全な参照。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.mapping_dry_run.catalog import MappingDryRunCatalog
from forecast_provider.mapping_dry_run.evidence_schema import InvalidReportError
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


def _publish(tmp_path, rows: list[str]):
    input_root = tmp_path / "input"
    input_root.mkdir()
    source = input_root / "secret-source.csv"
    source.write_text(
        "出荷日,JANコード,商品名称,出荷数量,数量単位,物流拠点,明細種別\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(json.dumps(_mapping(), ensure_ascii=False), encoding="utf-8")
    payload = collect_dry_run(
        input_root,
        source.name,
        mapping_file,
        now=lambda: datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
    )
    uri, checksum = publish_report(payload, tmp_path / "reports")
    return payload, tmp_path / "reports", checksum, uri


def test_catalog_returns_only_fixed_safe_fields(tmp_path):
    payload, root, checksum, _ = _publish(
        tmp_path,
        ["2026/09/01,0012345678901,秘密商品A,999999,個,秘密拠点,SHIPMENT"],
    )

    listing = MappingDryRunCatalog(root).list_reports()
    detail = MappingDryRunCatalog(root).get_report(checksum)

    assert listing["configured"] is True
    assert listing["valid_report_count"] == 1
    assert listing["invalid_report_count"] == 0
    assert len(listing["items"]) == 1
    assert detail is not None
    assert detail["outcome"] == "READY_FOR_NORMALIZATION"
    assert len(detail["checks"]) == 9
    assert set(detail["checks"][0]) == {"check_id", "status"}
    assert detail["dry_run_id"] == payload["dry_run_id"]
    encoded = json.dumps({"listing": listing, "detail": detail}, ensure_ascii=False)
    for secret in (
        "secret-source",
        "出荷日",
        "0012345678901",
        "秘密商品A",
        "999999",
        "秘密拠点",
        "file://",
    ):
        assert secret not in encoded


def test_catalog_sorts_reports_and_preserves_reason_codes(tmp_path):
    _, root, first, _ = _publish(
        tmp_path,
        ["bad-date,,秘密商品,-1,箱,秘密拠点,RETURN"],
    )
    report = MappingDryRunCatalog(root).get_report(first)

    assert report is not None
    assert report["outcome"] == "REVIEW_REQUIRED"
    assert report["observations"]["quarantine_reason_counts"] == {
        "INVALID_DATE": 1,
        "MISSING_JAN": 1,
        "NEGATIVE_QUANTITY": 1,
        "NON_SHIPMENT_ROW": 1,
        "UNIT_NOT_ALLOWED": 1,
    }


def test_catalog_skips_tampered_and_forged_reports(tmp_path):
    payload, root, checksum, _ = _publish(
        tmp_path,
        ["2026/09/01,001,商品,1,個,拠点,SHIPMENT"],
    )
    report_dir = root / "mapping-dry-run"
    original = report_dir / f"{checksum}.json"
    original.write_bytes(original.read_bytes() + b" ")
    forged = {**payload, "secret_raw_value": "漏えい値"}
    content = (json.dumps(forged, ensure_ascii=False, sort_keys=True) + "\n").encode()
    forged_hash = hashlib.sha256(content).hexdigest()
    (report_dir / f"{forged_hash}.json").write_bytes(content)

    listing = MappingDryRunCatalog(root).list_reports()

    assert listing["items"] == []
    assert listing["invalid_report_count"] == 2
    assert listing["valid_report_count"] == 0
    with pytest.raises(InvalidReportError):
        MappingDryRunCatalog(root).get_report(forged_hash)


def test_unconfigured_catalog_is_empty_and_limits_are_bounded():
    catalog = MappingDryRunCatalog(None)
    assert catalog.list_reports() == {
        "configured": False,
        "valid_report_count": 0,
        "invalid_report_count": 0,
        "items": [],
    }
    assert catalog.get_report("a" * 64) is None
    with pytest.raises(ValueError, match="limit"):
        catalog.list_reports(201)


def test_authenticated_api_lists_and_reads_verified_report(tmp_path):
    _, root, checksum, _ = _publish(
        tmp_path,
        ["2026/09/01,0012345678901,秘密商品,5,個,秘密拠点,SHIPMENT"],
    )
    database = tmp_path / "api.sqlite3"
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            mapping_dry_run_root=root,
        )
    )
    assert api.get("/api/mapping-dry-runs").status_code == 401
    api.headers["Authorization"] = "Bearer token"
    assert api.get("/api/mapping-dry-runs?limit=0").status_code == 422

    listing = api.get("/api/mapping-dry-runs")
    detail = api.get(f"/api/mapping-dry-runs/{checksum}")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["report_sha256"] == checksum
    assert detail.status_code == 200
    assert detail.json()["report_sha256"] == checksum
    assert api.get("/api/mapping-dry-runs/not-a-hash").status_code == 404
    assert "秘密商品" not in detail.text

    report_path = root / "mapping-dry-run" / f"{checksum}.json"
    report_path.write_bytes(report_path.read_bytes() + b" ")
    damaged = api.get(f"/api/mapping-dry-runs/{checksum}")
    assert damaged.status_code == 409
    assert damaged.json() == {"detail": "証跡のchecksumまたは形式が不正です"}
