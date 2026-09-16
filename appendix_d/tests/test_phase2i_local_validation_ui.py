"""Phase 2I: UI起点ローカルデータ検証job。"""

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.mapping_dry_run import (
    MappingDryRunProcessor,
    SqliteMappingDryRunJobStore,
)
from forecast_provider.normalization import SqliteNormalizationStore, make_mapping


def _mapping():
    return make_mapping(
        {
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
    )


def _client(tmp_path):
    database = tmp_path / "phase2i.sqlite3"
    mappings = SqliteNormalizationStore(database)
    mapping = _mapping()
    mappings.put_mapping(mapping)
    jobs = SqliteMappingDryRunJobStore(database)
    reports = tmp_path / "reports"
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            normalization=mappings,
            mapping_dry_run_root=reports,
            mapping_dry_run_jobs=jobs,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    return api, jobs, mappings, mapping, reports


def test_api_enqueues_worker_and_publishes_verified_report(tmp_path):
    api, jobs, mappings, mapping, reports = _client(tmp_path)
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "shipment.csv").write_text(
        "出荷日,JANコード,商品名称,出荷数量,数量単位,物流拠点,明細種別\n"
        "2026/09/01,0012345678901,秘密商品,5,個,秘密拠点,SHIPMENT\n",
        encoding="utf-8",
    )

    created = api.post(
        "/api/mapping-dry-run-jobs",
        json={
            "source_path": "shipment.csv",
            "mapping_id": mapping.mapping_id,
            "sample_rows": 100,
        },
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    assert api.get(f"/api/mapping-dry-run-jobs/{job_id}").json()["status"] == "QUEUED"

    assert MappingDryRunProcessor(jobs, mappings, input_root, reports).process_next() is True

    job = api.get(f"/api/mapping-dry-run-jobs/{job_id}").json()
    assert job["status"] == "SUCCEEDED"
    assert job["outcome"] == "READY_FOR_NORMALIZATION"
    report = api.get(f"/api/mapping-dry-runs/{job['report_sha256']}")
    assert report.status_code == 200
    assert report.json()["mapping_id"] == mapping.mapping_id
    assert "秘密商品" not in report.text
    assert "秘密拠点" not in report.text


def test_unsafe_source_produces_blocked_evidence_without_reading_outside_root(tmp_path):
    api, jobs, mappings, mapping, reports = _client(tmp_path)
    input_root = tmp_path / "input"
    input_root.mkdir()
    (tmp_path / "secret.csv").write_text("外部秘密値", encoding="utf-8")
    created = api.post(
        "/api/mapping-dry-run-jobs",
        json={"source_path": "../secret.csv", "mapping_id": mapping.mapping_id},
    )

    MappingDryRunProcessor(jobs, mappings, input_root, reports).process_next()

    job = api.get(f"/api/mapping-dry-run-jobs/{created.json()['id']}").json()
    assert job["status"] == "SUCCEEDED"
    assert job["outcome"] == "BLOCKED"
    response = api.get(f"/api/mapping-dry-runs/{job['report_sha256']}")
    assert response.json()["checks"][-1] == {
        "check_id": "SOURCE_PATH_SAFE",
        "status": "FAILED",
    }
    assert "外部秘密値" not in response.text


def test_job_api_rejects_unknown_mapping_and_requires_authentication(tmp_path):
    api, _, _, _, _ = _client(tmp_path)
    api.headers.clear()
    assert api.get("/api/mapping-dry-run-jobs").status_code == 401
    api.headers["Authorization"] = "Bearer token"
    response = api.post(
        "/api/mapping-dry-run-jobs",
        json={"source_path": "sample.csv", "mapping_id": "map-" + "0" * 64},
    )
    assert response.status_code == 422
    assert response.json()["message"] == "mappingが見つかりません"
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_store_claims_oldest_job_once(tmp_path):
    database = tmp_path / "store.sqlite3"
    store = SqliteMappingDryRunJobStore(database)
    first = store.enqueue("a.csv", "map-" + "1" * 64, "operator", 10)
    store.enqueue("b.csv", "map-" + "2" * 64, "operator", 20)

    claimed = store.claim()

    assert claimed is not None
    assert claimed.job_id == first.job_id
    assert claimed.status == "RUNNING"
    assert store.list_jobs()[0].status in {"QUEUED", "RUNNING"}
