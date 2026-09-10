"""候補API、別process Worker、確定選定版のPhase 1L結合試験。"""

import subprocess
import sys

from acceptance_support import build_three_product_daily
from fastapi.testclient import TestClient

from forecast_provider.api import create_app
from forecast_provider.jobs import SqliteRunStore
from forecast_provider.master import SqliteMasterStore, make_jan_mapping
from forecast_provider.selection import SqliteSelectionStore


def candidate_payload(build_id, business_product_id):
    return {
        "candidate_version": "candidate-v1",
        "daily_build_id": build_id,
        "business_product_ids": [business_product_id],
        "max_missing_rate": 0,
        "stable_cv_max": 0.8,
        "intermittent_zero_rate_min": 0.3,
        "requested_by": "operator@example.test",
        "purpose": "匿名3品目で選定手順を確認",
    }


def test_candidate_worker_and_immutable_initial_selection(tmp_path):
    database = tmp_path / "kiban.sqlite3"
    daily, catalog, products, build = build_three_product_daily(tmp_path, database)
    master = SqliteMasterStore(database)
    master.put_jan_mapping(
        make_jan_mapping(
            "003-new",
            products[2].canonical_product_id,
            "2026-01-01",
            None,
            "mapping-v1",
            "operator@example.test",
            "JAN変更を表す匿名fixture",
        )
    )
    selection = SqliteSelectionStore(database)
    api = TestClient(
        create_app(
            SqliteRunStore(database),
            catalog,
            "token",
            daily=daily,
            selection=selection,
        )
    )
    api.headers["Authorization"] = "Bearer token"
    created = api.post(
        "/api/selection-candidate-jobs",
        json=candidate_payload(build.build_id, products[1].canonical_product_id),
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    subprocess.run(
        [
            sys.executable,
            "-m",
            "forecast_provider.selection_worker",
            "--sqlite",
            str(database),
            "--once",
        ],
        check=True,
    )
    assert api.get(f"/api/selection-candidate-jobs/{job_id}").json()["status"] == "SUCCEEDED"
    candidates = api.get(
        f"/api/selection-candidate-jobs/{job_id}/candidates"
    ).json()
    assert len(candidates) == 3
    assert candidates[0]["business_designated"] is True
    assert abs(sum(float(item["quantity_share"]) for item in candidates) - 1) < 1e-12
    changed = next(
        item
        for item in candidates
        if item["canonical_product_id"] == products[2].canonical_product_id
    )
    assert changed["jan_changed"] is True
    assert "JAN_CHANGED" in changed["tags"]
    request = {
        "selection_version": "initial-selection-v1",
        "candidate_job_id": job_id,
        "scope": "INITIAL",
        "items": [
            {
                "canonical_product_id": product.canonical_product_id,
                "center_ids": ["C1"],
                "reason": f"匿名検証対象{index + 1}",
            }
            for index, product in enumerate(products)
        ],
        "selected_by": "operator@example.test",
        "rationale": "安定・間欠・JAN変更の選定手順を確認",
    }
    saved = api.post("/api/selections", json=request)
    assert saved.status_code == 201
    selection_id = saved.json()["id"]
    assert len(api.get(f"/api/selections/{selection_id}/items").json()) == 3
    request["rationale"] = "同じ版を変更"
    assert api.post("/api/selections", json=request).status_code == 409
