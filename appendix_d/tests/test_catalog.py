"""snapshot/experimentの版・不変性・fingerprint。"""

import sqlite3
from dataclasses import replace

import pytest
from test_run_api import experiment_payload, snapshot_payload

from forecast_provider.catalog import SqliteCatalogStore
from forecast_provider.catalog.domain import make_experiment, make_snapshot
from forecast_provider.jobs import SqliteRunStore


def test_snapshot_and_experiment_are_immutable(tmp_path):
    store = SqliteCatalogStore(tmp_path / "catalog.sqlite3")
    snapshot = make_snapshot(snapshot_payload())
    store.put_snapshot(snapshot)
    with pytest.raises(ValueError):
        store.put_snapshot(replace(snapshot, manifest={**snapshot.manifest, "seed": 9}))
    experiment = make_experiment(snapshot, experiment_payload(snapshot.snapshot_id))
    store.put_experiment(experiment)
    with pytest.raises(ValueError):
        store.put_experiment(replace(experiment, definition={**experiment.definition, "seed": 9}))


def test_reproducibility_inputs_change_identifiers():
    first = make_snapshot(snapshot_payload())
    changed_manifest = snapshot_payload()
    changed_manifest["selection_version"] = "selection-v2"
    second = make_snapshot(changed_manifest)
    assert first.snapshot_id != second.snapshot_id
    base = make_experiment(first, experiment_payload(first.snapshot_id))
    changed = experiment_payload(first.snapshot_id)
    changed["seed"] = 8
    assert base.condition_fingerprint != make_experiment(first, changed).condition_fingerprint
    assert (
        base.condition_fingerprint
        != make_experiment(second, experiment_payload(second.snapshot_id)).condition_fingerprint
    )


def test_catalog_schema_can_be_added_to_existing_run_database(tmp_path):
    path = tmp_path / "phase1e.sqlite3"
    SqliteRunStore(path)
    with sqlite3.connect(path) as db:
        before = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    SqliteCatalogStore(path)
    with sqlite3.connect(path) as db:
        after = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert before <= after
    assert {"dataset_snapshots", "experiments"} <= after
