import json

from portable.api.product_exclusions import ProductExclusions
from portable.runtime.paths import DataPaths


def test_full_jan_policy_preserves_original_and_can_restore(tmp_path):
    paths = DataPaths(tmp_path / "Data")
    paths.state.mkdir(parents=True)
    policy = ProductExclusions(paths)
    row = {"jan": "4901234567894", "quantity": "12", "exclude": False}
    policy.save(
        {
            "actor": "人工",
            "products": [
                {
                    "jan": row["jan"],
                    "exclude": True,
                    "product_name": "人工商品",
                    "reason": "試験対象外",
                }
            ],
        }
    )
    excluded = policy.apply([row])[0]
    assert excluded["exclude"] is True and excluded["quantity"] == "12"
    assert row["exclude"] is False
    assert policy.apply([{"jan": "567894"}])[0].get("exclude") is None
    policy.save(
        {"actor": "人工", "products": [{"jan": row["jan"], "exclude": False, "reason": "再対象化"}]}
    )
    assert policy.apply([excluded])[0]["exclude"] is False


def test_seed_is_imported_once_and_never_undoes_release(tmp_path):
    paths = DataPaths(tmp_path / "Data")
    paths.state.mkdir(parents=True)
    seed = {
        "format": "bunsen-product-exclusions-v1",
        "products": [
            {
                "jan": "4901234567894",
                "product_name": "人工商品",
                "exclude": True,
                "reason": "対象外",
            }
        ],
    }
    (paths.root.parent / "対象外商品設定.json").write_text(json.dumps(seed), encoding="utf-8")
    first = ProductExclusions(paths)
    assert first.list()[0]["exclude"] == 1
    first.save(
        {
            "actor": "人工",
            "products": [{"jan": "4901234567894", "exclude": False, "reason": "解除"}],
        }
    )
    assert ProductExclusions(paths).list()[0]["exclude"] == 0


def test_exclusion_is_view_overlay_and_approval_enforced(tmp_path):
    from portable.api.app import create_app
    from portable.api.document_ai import FIELDS

    app = create_app(tmp_path / "Data")
    service = app.state.documents
    doc = service.add("synthetic.pdf", b"%PDF-synthetic")
    row = {
        **dict.fromkeys(FIELDS, ""),
        "jan": "4901234567894",
        "kind": "shipment",
        "date": "2026-10-13",
        "location": "人工倉庫",
        "unit": "箱",
        "quantity": "2",
        "product_name": "人工商品",
        "case_factor": "1",
    }
    extraction = {"complete": True, "revision": "test", "rows": [row]}
    with service.db() as db:
        db.execute(
            "UPDATE documents SET extraction=? WHERE id=?", (json.dumps(extraction), doc["id"])
        )
    service.exclusions.save(
        {"actor": "人工", "products": [{"jan": row["jan"], "exclude": True, "reason": "対象外"}]}
    )
    assert service.get(doc["id"])["extraction"]["rows"][0].get("exclude") is None
    assert service.list()[0]["extraction"]["rows"][0]["exclude"] is True
    service.approve(
        doc["id"], {"actor": "人工", "confirmed": True, "revision": "test", "rows": [row]}
    )
    assert service.get(doc["id"])["approval"]["files"] == []
