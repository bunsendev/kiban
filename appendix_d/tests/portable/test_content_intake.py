import io
import zipfile
from contextlib import nullcontext
from datetime import date

import pytest

from portable.api.business_archive import ArchiveError, analyze_archive
from portable.api.drop_folder import DropFolderIntake
from portable.api.formal_shipment_daily import _shipment_file_dates
from portable.api.inventory_handoff import inventory_centers
from portable.runtime.paths import DataPaths


def files():
    return {
        "export001.csv": (
            "倉庫,基準日,出荷日,JAN,数量\n神戸,2026/02/04,2026/02/04,4901234567894,2\n"
        ).encode("cp932"),
        "export002.csv": (
            "倉庫,基準日,商品コード,明細バラ数,賞味期限\n"
            "神戸,2026/02/04,4901234567894,10,2026/04/30\n"
        ).encode("utf-8-sig"),
    }


def archive_bytes(values):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in values.items():
            archive.writestr(name, raw)
    return output.getvalue()


def test_generic_names_work_for_preflight_and_formal_readers(tmp_path):
    raw = archive_bytes(files())
    report = analyze_archive(raw, tmp_path / "prepared.csv")
    assert report["files"] == {"shipment": 1, "inventory": 1, "ignored": 0}
    assert report["prepared_rows"] == 1
    path = tmp_path / "original.zip"
    path.write_bytes(raw)
    assert inventory_centers(path) == [{"source_center": "神戸", "latest_date": "2026-02-04"}]
    assert _shipment_file_dates(raw, {"神戸"}) == {"神戸": {date(2026, 2, 4)}}


def test_metadata_is_required_not_guessed_from_generic_name(tmp_path):
    raw = archive_bytes(
        {
            "random.csv": "JAN,数量,出荷日\n4901234567894,2,2026/02/04\n".encode()
        }
    )
    with pytest.raises(ArchiveError, match="倉庫を特定できません"):
        analyze_archive(raw, tmp_path / "prepared.csv")


def test_row_dates_do_not_imply_complete_export(tmp_path):
    raw = archive_bytes(
        {"a.csv": "倉庫,出荷日,JAN,数量\n神戸,2026/02/04,4901234567894,2\n".encode()}
    )
    report = analyze_archive(raw, tmp_path / "prepared.csv")
    assert report["prepared_rows"] == 1
    assert report["center_windows"] == []
    assert _shipment_file_dates(raw, {"神戸"}) == {}


def test_folder_csv_batch_preserves_originals_and_waits_for_shipment(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("portable.api.drop_folder.time.monotonic", lambda: clock[0])
    paths = DataPaths(tmp_path)
    paths.incoming.mkdir(parents=True)
    calls = []

    def ingest(raw):
        calls.append(raw)
        return {"analysis_id": "a" * 64, **analyze_archive(raw, tmp_path / "prepared.csv")}

    intake = DropFolderIntake(paths, ingest, active=nullcontext)
    values = files()
    (paths.incoming / "export002.csv").write_bytes(values["export002.csv"])
    assert intake.scan(force=True)["handled"] == []
    assert "待っています" in intake.view()["csv_message"]
    (paths.incoming / "export001.csv").write_bytes(values["export001.csv"])
    assert intake.scan()["handled"] == []
    clock[0] += 11
    result = intake.scan()
    assert result["handled"][0]["status"] == "PROCESSED"
    with zipfile.ZipFile(io.BytesIO(calls[0])) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == values
    assert not list(paths.incoming.glob("*.csv"))
    assert len(list(intake.processed.glob("*.csv"))) == 2
    assert intake.scan(force=True)["handled"] == []
