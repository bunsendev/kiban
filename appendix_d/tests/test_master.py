"""JAN名寄せ候補、承認監査、有効期間のPhase 1I契約。"""

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.ingestion import ImportProcessor, SqliteIngestionStore
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.master import (
    MatchingProcessor,
    SqliteMasterStore,
    generate_candidates,
    make_decision,
    make_handling_period,
    make_jan_mapping,
    make_matching_job,
    make_product,
    normalize_product_name,
)
from forecast_provider.normalization import (
    NormalizationProcessor,
    SqliteNormalizationStore,
    make_mapping,
)


def _mapping_definition():
    return {
        "date_column": "出荷日",
        "jan_column": "JAN",
        "product_name_column": "商品名",
        "quantity_column": "数量",
        "unit_column": "単位",
        "center_column": "センター",
        "date_formats": ["%Y/%m/%d"],
        "allowed_units": ["PACK"],
        "availability_mode": "ASSUMED",
        "file_mode": "FULL",
    }


def _normalized(tmp_path, content):
    input_root = tmp_path / "input"
    input_root.mkdir()
    source = input_root / "shipments.csv"
    source.write_text(content, encoding="utf-8")
    database = tmp_path / "kiban.sqlite3"
    ingestion = SqliteIngestionStore(database)
    imported = ingestion.enqueue("shipments.csv")
    ImportProcessor(ingestion, input_root, tmp_path / "archive").process_next()
    source_file = ingestion.list_files(imported.import_id)[0]
    normalization = SqliteNormalizationStore(database)
    mapping = make_mapping(_mapping_definition())
    normalization.put_mapping(mapping)
    job = normalization.enqueue(source_file.source_file_id, mapping.mapping_id)
    assert NormalizationProcessor(normalization, ingestion).process_next().status == "SUCCEEDED"
    return database, source, ingestion, normalization, source_file, job


def _candidate_environment(tmp_path):
    content = (
        "出荷日,JAN,商品名,数量,単位,センター\n"
        "2026/01/01,0012345678901,商品 500ml,4,PACK,C1\n"
        "2026/01/02,0012345678901,商品 500ml,3,PACK,C2\n"
        "2026/01/04,0012345678902,商品　５００ＭＬ,5,PACK,C1\n"
    )
    database, source, ingestion, normalization, source_file, normalized = _normalized(
        tmp_path, content
    )
    master = SqliteMasterStore(database)
    job = make_matching_job(
        {
            "normalization_ids": [normalized.normalization_id],
            "policy_version": "jan-candidate-v1",
            "similarity_threshold": 0.85,
            "handoff_similarity_threshold": 0.6,
            "max_handoff_gap_days": 31,
        }
    )
    master.put_job(job)
    assert MatchingProcessor(master).process_next().status == "SUCCEEDED"
    return database, source, ingestion, normalization, source_file, normalized, master, job


def test_candidate_generation_is_deterministic_and_does_not_auto_map(tmp_path):
    *_, master, job = _candidate_environment(tmp_path)
    candidates = master.list_candidates(job.matching_job_id)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.left_jan == "0012345678901"
    assert candidate.right_jan == "0012345678902"
    assert candidate.details["reasons"] == ["SAME_NORMALIZED_NAME", "DATE_HANDOFF"]
    assert candidate.details["gap_days"] == 1
    assert candidate.details["left_center_quantities"] == {"C1": "4", "C2": "3"}
    assert candidate.details["right_center_quantities"] == {"C1": "5"}
    assert candidate.details["left_center_daily_quantities"] == {
        "C1": [{"date": "2026-01-01", "quantity": "4"}],
        "C2": [{"date": "2026-01-02", "quantity": "3"}],
    }
    assert master.list_jan_mappings() == []
    rows = master.source_rows(job)
    assert generate_candidates(job, rows) == generate_candidates(job, list(reversed(rows)))
    assert normalize_product_name(" 商品　５００ｍｌ ") == "商品 500ml"


def test_matching_job_id_treats_normalization_ids_as_a_set():
    definition = {
        "normalization_ids": ["normalization-b", "normalization-a"],
        "policy_version": "jan-candidate-v1",
        "similarity_threshold": 0.85,
        "handoff_similarity_threshold": 0.6,
        "max_handoff_gap_days": 31,
    }
    first = make_matching_job(definition)
    second = make_matching_job(
        {**definition, "normalization_ids": list(reversed(definition["normalization_ids"]))}
    )
    assert first == second
    assert first.definition["normalization_ids"] == ["normalization-a", "normalization-b"]


def test_date_handoff_uses_its_own_similarity_threshold():
    job = make_matching_job(
        {
            "normalization_ids": ["normalization-a"],
            "policy_version": "jan-candidate-v1",
            "similarity_threshold": 0.99,
            "handoff_similarity_threshold": 0.5,
            "max_handoff_gap_days": 7,
        }
    )
    rows = [
        {
            "raw_jan": "001",
            "raw_product_name": "商品ABC 500ml",
            "shipment_date": "2026-01-01",
            "unit": "PACK",
            "center_id": "C1",
            "quantity": "1",
        },
        {
            "raw_jan": "002",
            "raw_product_name": "商品ABD 500ml",
            "shipment_date": "2026-01-03",
            "unit": "PACK",
            "center_id": "C1",
            "quantity": "1",
        },
    ]
    candidate = generate_candidates(job, rows)[0]
    assert candidate.details["reasons"] == ["DATE_HANDOFF"]
    assert generate_candidates(job, [{**rows[0]}, {**rows[1], "shipment_date": "2026-02-01"}]) == []


def test_all_decisions_are_validated_and_audited(tmp_path):
    *_, master, job = _candidate_environment(tmp_path)
    candidate_id = master.list_candidates(job.matching_job_id)[0].candidate_id
    left = make_product("商品500ml", "master@example.test", "初回登録")
    right = make_product("後継商品500ml", "master@example.test", "後継登録")
    master.put_product(left)
    master.put_product(right)
    values = [
        make_decision(
            candidate_id,
            "SAME_PRODUCT",
            left.canonical_product_id,
            left.canonical_product_id,
            "mapping-v1",
            "approver@example.test",
            "同一規格を確認",
        ),
        make_decision(
            candidate_id,
            "DIFFERENT_PRODUCT",
            left.canonical_product_id,
            right.canonical_product_id,
            "mapping-v2",
            "approver@example.test",
            "併売を確認",
        ),
        make_decision(
            candidate_id,
            "SUCCESSOR",
            left.canonical_product_id,
            right.canonical_product_id,
            "mapping-v3",
            "approver@example.test",
            "切替通知を確認",
        ),
        make_decision(
            candidate_id,
            "UNRESOLVED",
            None,
            None,
            "mapping-v4",
            "approver@example.test",
            "追加資料待ち",
        ),
    ]
    for value in values:
        master.put_decision(value)
    audit = master.list_decisions(candidate_id)
    by_version = {item["mapping_version"]: item for item in audit}
    assert [by_version[f"mapping-v{number}"]["decision"] for number in range(1, 5)] == [
        "SAME_PRODUCT",
        "DIFFERENT_PRODUCT",
        "SUCCESSOR",
        "UNRESOLVED",
    ]
    assert by_version["mapping-v1"]["approved_by"] == "approver@example.test"
    assert by_version["mapping-v1"]["reason"] == "同一規格を確認"
    with pytest.raises(ValueError, match="同じcanonical product"):
        make_decision(
            candidate_id,
            "SAME_PRODUCT",
            left.canonical_product_id,
            right.canonical_product_id,
            "mapping-v5",
            "approver@example.test",
            "不正な指定",
        )
    with pytest.raises(ValueError, match="変更できません"):
        master.put_decision(values[0])


def test_inclusive_jan_and_handling_periods_reject_overlap(tmp_path):
    *_, master, _ = _candidate_environment(tmp_path)
    product = make_product("商品500ml", "master@example.test", "初回登録")
    master.put_product(product)
    first = make_jan_mapping(
        "0012345678901",
        product.canonical_product_id,
        "2026-01-01",
        "2026-01-31",
        "mapping-v1",
        "approver@example.test",
        "JAN確認",
    )
    master.put_jan_mapping(first)
    with pytest.raises(ValueError, match="競合"):
        master.put_jan_mapping(
            make_jan_mapping(
                first.jan,
                product.canonical_product_id,
                "2026-01-31",
                "2026-02-28",
                "mapping-v1",
                "approver@example.test",
                "境界重複",
            )
        )
    master.put_jan_mapping(
        make_jan_mapping(
            first.jan,
            product.canonical_product_id,
            "2026-02-01",
            None,
            "mapping-v1",
            "approver@example.test",
            "翌日から切替",
        )
    )
    period = make_handling_period(
        product.canonical_product_id,
        "C1",
        "2026-01-01",
        "2026-01-31",
        "CONFIRMED",
        "period-v1",
        "approver@example.test",
        "出荷実績",
    )
    master.put_handling_period(period)
    with pytest.raises(ValueError, match="競合"):
        master.put_handling_period(
            make_handling_period(
                product.canonical_product_id,
                "C1",
                "2026-01-31",
                None,
                "TENTATIVE",
                "period-v1",
                "approver@example.test",
                "予定表",
            )
        )


def test_superseded_source_normalization_cannot_start_matching(tmp_path):
    header = "出荷日,JAN,商品名,数量,単位,センター\n"
    database, source, ingestion, normalization, original, normalized = _normalized(
        tmp_path, header + "2026/01/01,001,商品A,4,PACK,C1\n"
    )
    master = SqliteMasterStore(database)
    job = make_matching_job(
        {
            "normalization_ids": [normalized.normalization_id],
            "policy_version": "jan-candidate-v1",
            "similarity_threshold": 0.85,
            "handoff_similarity_threshold": 0.6,
            "max_handoff_gap_days": 31,
        }
    )
    master.put_job(job)
    source.write_text(header + "2026/01/01,001,商品A,5,PACK,C1\n", encoding="utf-8")
    imported = ingestion.enqueue("shipments.csv")
    ImportProcessor(ingestion, tmp_path / "input", tmp_path / "archive").process_next()
    correction = ingestion.list_files(imported.import_id)[0]
    normalization.select_source(
        correction.logical_path,
        correction.source_file_id,
        "selection-v2",
        "approver@example.test",
        "訂正版を採用",
    )
    result = MatchingProcessor(master).process_next()
    assert result.status == "FAILED"
    assert "現在採用中ではない" in result.error
    with pytest.raises(ValueError, match="現在採用中ではない"):
        master.put_job(job)
    assert original.source_file_id != correction.source_file_id


def test_api_to_separate_matching_worker_and_approval_endpoints(tmp_path):
    database, *_, master, normalized_job = _candidate_environment_unprocessed(tmp_path)
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            master=master,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    created = api.post(
        "/api/matching/jobs",
        json={"normalization_ids": [normalized_job.normalization_id]},
    )
    assert created.status_code == 202
    jobs = api.get("/api/matching/jobs")
    assert jobs.status_code == 200
    assert jobs.json()[0]["matching_job_id"] == created.json()["id"]
    assert jobs.json()[0]["status"] == "QUEUED"
    assert jobs.json()[0]["candidate_count"] == 0
    subprocess.run(
        [
            sys.executable,
            "-m",
            "forecast_provider.matching_worker",
            "--sqlite",
            str(database),
            "--once",
        ],
        check=True,
    )
    result = api.get(f"/api/matching/jobs/{created.json()['id']}")
    assert result.status_code == 200
    assert result.json()["status"] == "SUCCEEDED"
    assert api.get("/api/matching/jobs").json()[0]["status"] == "SUCCEEDED"
    assert len(result.json()["candidates"]) == 1
    assert api.get("/api/matching/jobs").json()[0]["candidate_count"] == 1
    candidate_id = result.json()["candidates"][0]["candidate_id"]
    product = api.post(
        "/api/products",
        json={
            "display_name": "商品500ml",
            "created_by": "master@example.test",
            "reason": "名寄せ承認用",
        },
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    decision = api.post(
        "/api/matching/decisions",
        json={
            "candidate_id": candidate_id,
            "decision": "SAME_PRODUCT",
            "left_product_id": product_id,
            "right_product_id": product_id,
            "mapping_version": "mapping-v1",
            "approved_by": "approver@example.test",
            "reason": "同一商品と確認",
        },
    )
    assert decision.status_code == 201
    jan_mapping = api.post(
        "/api/jan-mappings",
        json={
            "jan": "0012345678901",
            "canonical_product_id": product_id,
            "valid_from": "2026-01-01",
            "valid_to": "2026-01-31",
            "mapping_version": "mapping-v1",
            "approved_by": "approver@example.test",
            "reason": "JAN切替資料を確認",
        },
    )
    assert jan_mapping.status_code == 201
    handling = api.post(
        "/api/handling-periods",
        json={
            "canonical_product_id": product_id,
            "center_id": "C1",
            "valid_from": "2026-01-01",
            "valid_to": None,
            "status": "TENTATIVE",
            "period_version": "period-v1",
            "approved_by": "approver@example.test",
            "basis": "初回出荷日",
        },
    )
    assert handling.status_code == 201
    assert (
        len(
            api.get(
                "/api/matching/candidates", params={"matching_job_id": created.json()["id"]}
            ).json()
        )
        == 1
    )
    assert len(api.get("/api/jan-mappings", params={"mapping_version": "mapping-v1"}).json()) == 1
    assert len(api.get("/api/handling-periods", params={"period_version": "period-v1"}).json()) == 1
    assert api.get("/api/jan-mappings").json()[0]["approved_by"] == "local-admin"


def _candidate_environment_unprocessed(tmp_path):
    content = (
        "出荷日,JAN,商品名,数量,単位,センター\n"
        "2026/01/01,0012345678901,商品 500ml,4,PACK,C1\n"
        "2026/01/04,0012345678902,商品　５００ＭＬ,5,PACK,C1\n"
    )
    database, source, ingestion, normalization, source_file, job = _normalized(tmp_path, content)
    return database, source, ingestion, normalization, source_file, SqliteMasterStore(database), job
