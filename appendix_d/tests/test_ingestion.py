"""原本取込の安全性・不変性・重複/訂正判定。"""

import io
import subprocess
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.ingestion import ImportProcessor, SqliteIngestionStore
from forecast_provider.ingestion.processor import detect_encoding, detect_stream_encoding
from forecast_provider.jobs import SqliteRunStore


def setup_ingestion(tmp_path):
    inputs = tmp_path / "input"
    inputs.mkdir()
    store = SqliteIngestionStore(tmp_path / "ledger.sqlite3")
    return inputs, store, ImportProcessor(store, inputs, tmp_path / "archive")


def test_stream_encoding_probe_does_not_split_cp932_character() -> None:
    payload = b"header\n" + (b"a" * 131_064) + "あ".encode("cp932") + b"\n"
    assert detect_encoding(payload[:131_072])[0] is None
    assert detect_stream_encoding(io.BytesIO(payload))[0] == "cp932"


def test_folder_import_preserves_original(tmp_path):
    inputs, store, processor = setup_ingestion(tmp_path)
    batch = inputs / "batch"
    batch.mkdir()
    raw = "日付,JAN,数量\n2026-01-01,00123,4\n".encode("cp932")
    (batch / "shipments.csv").write_bytes(raw)
    job = store.enqueue("batch")
    result = processor.process_next()
    assert result is not None and result.import_id == job.import_id
    assert result.status == "SUCCEEDED" and result.accepted_count == 1
    record = store.list_files(job.import_id)[0]
    assert record.encoding == "cp932" and record.status == "ACCEPTED"
    assert Path(record.stored_path).read_bytes() == raw


def test_duplicate_and_correction_candidate(tmp_path):
    inputs, store, processor = setup_ingestion(tmp_path)
    source = inputs / "shipments.csv"
    source.write_text("date,jan,quantity\n2026-01-01,00123,4\n", encoding="utf-8")
    first = store.enqueue("shipments.csv")
    processor.process_next()
    duplicate = store.enqueue("shipments.csv")
    processor.process_next()
    duplicate_record = store.list_files(duplicate.import_id)[0]
    assert duplicate_record.status == "DUPLICATE"
    assert duplicate_record.duplicate_of == store.list_files(first.import_id)[0].source_file_id

    source.write_text("date,jan,quantity\n2026-01-01,00123,5\n", encoding="utf-8")
    correction = store.enqueue("shipments.csv")
    processor.process_next()
    record = store.list_files(correction.import_id)[0]
    assert record.status == "CORRECTION_CANDIDATE"
    assert record.correction_of == store.list_files(first.import_id)[0].source_file_id


def test_bad_file_is_quarantined_without_stopping_other_files(tmp_path):
    inputs, store, processor = setup_ingestion(tmp_path)
    batch = inputs / "batch"
    batch.mkdir()
    (batch / "good.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (batch / "bad.csv").write_bytes(b"\x81")
    store.enqueue("batch")
    result = processor.process_next()
    assert result is not None and result.status == "SUCCEEDED"
    assert result.accepted_count == 1 and result.quarantined_count == 1


def test_zip_traversal_fails_whole_job(tmp_path):
    inputs, store, processor = setup_ingestion(tmp_path)
    with zipfile.ZipFile(inputs / "bad.zip", "w") as archive:
        archive.writestr("../escape.csv", "bad")
    job = store.enqueue("bad.zip")
    result = processor.process_next()
    assert result is not None and result.status == "FAILED"
    assert "逸脱" in result.error
    assert store.list_files(job.import_id) == []


def test_api_to_separate_import_worker(tmp_path):
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "shipment.csv").write_text("date,jan,quantity\n2026-01-01,00123,4\n")
    database = tmp_path / "kiban.sqlite3"
    ingestion = SqliteIngestionStore(database)
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            SqliteCatalogStore(database),
            "token",
            ingestion=ingestion,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    created = api.post("/api/imports", json={"source_path": "shipment.csv"})
    assert created.status_code == 202
    queued = api.get("/api/imports")
    assert queued.status_code == 200
    assert queued.json() == [
        {
            "import_id": created.json()["id"],
            "source_path": "shipment.csv",
            "status": "QUEUED",
            "file_count": 0,
            "accepted_count": 0,
            "quarantined_count": 0,
            "duplicate_count": 0,
            "error": None,
        }
    ]

    subprocess.run(
        [
            sys.executable,
            "-m",
            "forecast_provider.ingestion_worker",
            "--sqlite",
            str(database),
            "--input-root",
            str(inputs),
            "--archive-root",
            str(tmp_path / "archive"),
            "--once",
        ],
        check=True,
    )
    result = api.get(f"/api/imports/{created.json()['id']}")
    assert result.status_code == 200
    assert result.json()["status"] == "SUCCEEDED"
    assert result.json()["files"][0]["status"] == "ACCEPTED"
    assert api.get("/api/imports").json()[0]["accepted_count"] == 1
