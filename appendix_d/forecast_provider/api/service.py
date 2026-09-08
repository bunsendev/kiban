"""run操作のアプリケーションサービス。HTTPへ依存しない。"""

from __future__ import annotations

import uuid

from ..jobs import Expectation, OriginDefinition, RunDefinition, RunSnapshot
from ..jobs.contracts import RunStore
from .schemas import RunCreate


class RunNotFoundError(KeyError):
    pass


class RunService:
    def __init__(self, store: RunStore) -> None:
        self.store = store

    def create(self, request: RunCreate) -> RunSnapshot:
        run_id = str(uuid.uuid4())
        origins = tuple(OriginDefinition(x.origin_date, x.cutoff_at) for x in request.origins)
        expectations = tuple(
            Expectation(x.unique_id, x.origin_date, x.target_date, x.horizon)
            for x in request.expectations
        )
        self.store.create_run(
            RunDefinition(
                run_id,
                request.experiment_id,
                request.condition_fingerprint,
                request.provider_id,
                request.model_name,
                request.seed,
            ),
            origins,
            expectations,
        )
        return self.get(run_id)

    def get(self, run_id: str) -> RunSnapshot:
        snapshot = self.store.get_run(run_id)
        if snapshot is None:
            raise RunNotFoundError(run_id)
        return snapshot

    def cancel(self, run_id: str) -> RunSnapshot:
        self.get(run_id)
        self.store.request_cancellation(run_id)
        return self.get(run_id)

    def resume(self, run_id: str, condition_fingerprint: str) -> RunSnapshot:
        self.get(run_id)
        self.store.start_or_resume(run_id, condition_fingerprint)
        return self.get(run_id)
