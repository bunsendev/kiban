"""checksum検証後も、保存形式・学習条件・参照関係を検証する。"""

from dataclasses import replace
from datetime import timedelta

import pandas as pd
import pytest

from forecast_provider.artifacts import (
    ArtifactError,
    ForecastArtifactRepository,
    LocalArtifactStore,
)
from forecast_provider.artifacts import json_format as jf
from forecast_provider.artifacts.contracts import reference_for
from forecast_provider.errors import ContractViolationError
from forecast_provider.providers.baseline_codec import BuiltinBaselineCodec
from forecast_provider.providers.builtin_baseline import BuiltinBaselineProvider


@pytest.fixture
def saved(phase1a_case, tmp_path):
    data, ds, config, parent = phase1a_case
    config = replace(config, interval_levels=(0.8,))
    repo = ForecastArtifactRepository(LocalArtifactStore(tmp_path), [BuiltinBaselineCodec()])
    provider = BuiltinBaselineProvider()
    model = provider.fit_parameters(
        data[data.ds.le(pd.Timestamp(ds.train_end))], ds, config, parent
    )
    ticket = repo.save_model(model, ds, config, parent)
    ctx = parent.for_origin(ds.origin_dates()[1])
    ref = provider.refresh_context(
        model, data[data.ds.le(pd.Timestamp(ctx.origin_date))], ctx.origin_date, ctx
    )
    context_ticket = repo.save_context(ref, ticket, ds, config, ctx)
    return repo, model, ticket, context_ticket, ds, config, parent, ctx


@pytest.mark.parametrize(
    "path,value",
    [
        (("format_version",), 2),
        (("format_version",), True),
        (("codec_version",), 2),
        (("kind",), "context"),
        (("provider_id",), "unknown"),
        (("binding", "run_id"), "other"),
        (("binding", "experiment_id"), "other"),
        (("metadata", "provider_version"), "other"),
        (("metadata", "model_name"), "other"),
        (("metadata", "parameter_fingerprint"), "a" * 64),
        (("metadata", "fitted_at"), "2026-01-01T00:00:00"),
        (("metadata", "weights_id"), "fake-weight"),
        (("state", "seed"), 0),
        (("state", "run_id"), "other"),
        (("state", "dataset_unique_ids"), ["A", "A"]),
        (("state", "train_series", "A", "start"), "2026-01-01"),
        (("state", "train_series", "A", "values"), [True]),
        (("state", "train_series", "A", "values"), [-1]),
        (("state", "residual_quantiles", "A"), [[1, 0.1, 1.0], [1, 0.1, 2.0]]),
        (("state", "residual_quantiles", "A"), [[1, 0.1, 1.0]]),
    ],
)
def test_rejects_invalid_model_even_with_recomputed_checksum(saved, path, value):
    repo, _, ticket, _, ds, config, parent, _ = saved
    document = jf.loads(repo.store.get(ticket))
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    changed = repo.store.put(jf.dumps(document))
    with pytest.raises(ContractViolationError):
        repo.load_model(changed, ds, config, parent)


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_snapshot_id", "other"),
        ("selection_version", "other"),
        ("train_start", pd.Timestamp("2024-01-02").date()),
        ("unique_ids", ("A",)),
    ],
)
def test_load_model_rejects_other_dataset_conditions(saved, field, value):
    repo, _, ticket, _, ds, config, parent, _ = saved
    with pytest.raises(ArtifactError, match="不一致"):
        repo.load_model(ticket, replace(ds, **{field: value}), config, parent)


def test_load_model_rejects_other_preprocessing_seed_and_run(saved):
    repo, _, ticket, _, ds, config, parent, _ = saved
    with pytest.raises(ArtifactError):
        repo.load_model(ticket, ds, replace(config, preprocessing_version="other"), parent)
    for field, value in (("seed", 43), ("run_id", "other"), ("experiment_id", "other")):
        with pytest.raises(ArtifactError):
            repo.load_model(ticket, ds, config, replace(parent, **{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_id", "other"),
        ("origin_date", "2026-01-11"),
        ("cutoff_at", "2026-01-11T01:00:00+09:00"),
        ("history_end", "2026-01-12"),
    ],
)
def test_context_rejects_metadata_mismatch(saved, field, value):
    repo, _, ticket, context_ticket, ds, config, _, ctx = saved
    document = jf.loads(repo.store.get(context_ticket))
    document["metadata"][field] = value
    changed = repo.store.put(jf.dumps(document))
    with pytest.raises(ContractViolationError):
        repo.load_context(changed, ticket, ds, config, ctx)


def test_context_binds_exact_model_artifact_and_origin(saved):
    repo, model, ticket, context_ticket, ds, config, parent, ctx = saved
    other = repo.save_model(replace(model, model_id="new-model"), ds, config, parent)
    with pytest.raises(ArtifactError, match="model artifact"):
        repo.load_context(context_ticket, other, ds, config, ctx)
    with pytest.raises(ContractViolationError, match="origin_date"):
        repo.load_context(
            context_ticket, ticket, ds, config, ctx.for_origin(ctx.origin_date + timedelta(days=1))
        )
    document = jf.loads(repo.store.get(context_ticket))
    document["state"]["series"]["A"]["start"] = "2026-01-01"
    changed = repo.store.put(jf.dumps(document))
    with pytest.raises(ArtifactError, match="history_end"):
        repo.load_context(changed, ticket, ds, config, ctx)


@pytest.mark.parametrize(
    "payload", [b"not json", b'{"x": 1, "x": 2}', b'{"x": NaN}', b"[]", b"\xff"]
)
def test_bad_json_is_rejected(saved, payload):
    repo, _, _, _, ds, config, parent, _ = saved
    with pytest.raises(ArtifactError):
        repo.load_model(repo.store.put(payload), ds, config, parent)


def test_codec_and_store_are_injected_and_store_output_is_verified(saved):
    repo, _, ticket, _, ds, config, parent, _ = saved
    with pytest.raises(ArtifactError, match="codec"):
        ForecastArtifactRepository(repo.store, [BuiltinBaselineCodec(), BuiltinBaselineCodec()])
    with pytest.raises(ArtifactError, match="provider"):
        ForecastArtifactRepository(repo.store, []).load_model(ticket, ds, config, parent)

    class MemoryStore:
        def __init__(self):
            self.objects = {}

        def put(self, data):
            ref = reference_for(data)
            self.objects[ref.sha256] = data
            return ref

        def get(self, ref):
            return self.objects[ref.sha256]

    memory = MemoryStore()
    memory.put(repo.store.get(ticket))
    other = ForecastArtifactRepository(memory, [BuiltinBaselineCodec()])
    assert other.load_model(ticket, ds, config, parent).model_id == saved[1].model_id
    memory.objects[ticket.sha256] = b"{}"
    with pytest.raises(ArtifactError, match="checksum"):
        other.load_model(ticket, ds, config, parent)
