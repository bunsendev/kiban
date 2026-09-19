"""複数OSSモデルを既存の実験・適合試験・run台帳へ一括登録する。"""

import hashlib
import json
import uuid
from dataclasses import asdict

from ..comparison_campaign import CampaignEntry
from ..errors import ProviderError
from ..registry import registry
from .campaign_results import build_campaign_results
from .campaign_schemas import ComparisonCampaignCreate
from .schemas import ExperimentCreate

RUN_NAMESPACE = uuid.UUID("e4854d6e-a764-42dc-84a7-79d381348364")


class CampaignNotFound(KeyError):
    pass


class ComparisonCampaignService:
    def __init__(self, campaigns, application, conformance, evaluation=None) -> None:
        self.campaigns = campaigns
        self.application = application
        self.conformance = conformance
        self.evaluation = evaluation

    def create(self, request, requested_by: str) -> dict:
        self.application.get_snapshot(request.snapshot_id)
        definitions = [self._definition(request.snapshot_id, item) for item in request.models]
        experiments = [
            self.application.prepare_experiment(definition) for definition in definitions
        ]
        model_keys = json.dumps(
            sorted(f"{item.provider_id}/{item.model_id}" for item in request.models),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        request_key_hash = hashlib.sha256(request.request_key.encode("utf-8")).hexdigest()
        campaign, _created = self.campaigns.reserve(
            request_key_hash, request.snapshot_id, requested_by, request.purpose,
            model_keys, request.mode, request.horizon, request.policy_version,
        )
        existing = {
            (entry.provider_id, entry.model_id): entry
            for entry in self.campaigns.list_entries(campaign.campaign_id)
        }
        for definition, prepared in zip(definitions, experiments, strict=True):
            key = (definition.provider_id, definition.model_name)
            if key in existing:
                continue
            experiment = self.application.save_experiment(prepared)
            job = self._ensure_conformance(experiment.experiment_id, requested_by)
            run_id = str(uuid.uuid5(RUN_NAMESPACE, f"{campaign.campaign_id}:{key[0]}:{key[1]}"))
            run = self.application.ensure_run(experiment.experiment_id, run_id)
            entry = CampaignEntry(
                campaign.campaign_id,
                key[0],
                key[1],
                experiment.experiment_id,
                job.job_id,
                run.run_id,
            )
            self.campaigns.put_entry(entry)
        return self.detail(campaign.campaign_id)

    def create_batch(self, request, requested_by: str) -> dict:
        """保存済みsnapshot群へ同じ比較条件を再送可能な形で登録する。"""
        for snapshot_id in request.snapshot_ids:
            self.application.get_snapshot(snapshot_id)
        campaigns = []
        for index, snapshot_id in enumerate(request.snapshot_ids):
            child_key = hashlib.sha256(
                f"{request.request_key}:{index}".encode()
            ).hexdigest()
            campaigns.append(
                self.create(
                    ComparisonCampaignCreate(
                        request_key=child_key,
                        snapshot_id=snapshot_id,
                        models=request.models,
                        purpose=request.purpose,
                        mode=request.mode,
                        horizon=request.horizon,
                        policy_version=request.policy_version,
                    ),
                    requested_by,
                )
            )
        return {"campaign_count": len(campaigns), "campaigns": campaigns}

    def _definition(self, snapshot_id: str, selection) -> ExperimentCreate:
        try:
            metadata = registry.create(selection.provider_id).metadata()
        except ProviderError as exc:
            raise ValueError(f"未登録Providerです: {selection.provider_id}") from exc
        if metadata.get_model(selection.model_id) is None:
            raise ValueError(
                f"Providerにモデルがありません: {selection.provider_id}/{selection.model_id}"
            )
        defaults = metadata.experiment_defaults
        return ExperimentCreate(
            snapshot_id=snapshot_id,
            provider_id=selection.provider_id,
            model_name=selection.model_id,
            params=defaults.params,
            interval_levels=defaults.interval_levels,
            preprocessing_version=defaults.preprocessing_version,
            seed=defaults.seed,
            resource_profile=defaults.resource_profile,
            training_policy=defaults.training_policy,
        )

    def _ensure_conformance(self, experiment_id: str, requested_by: str):
        previous = self.conformance.list(experiment_id)
        reusable = next(
            (item for item in previous if item.status in {"QUEUED", "RUNNING", "SUCCEEDED"}),
            None,
        )
        return reusable or self.conformance.enqueue(experiment_id, requested_by)

    def get(self, campaign_id: str):
        value = self.campaigns.get(campaign_id)
        if value is None:
            raise CampaignNotFound(campaign_id)
        return value

    def list(self, *, limit: int = 100) -> list[dict]:
        return [self.detail(item.campaign_id) for item in self.campaigns.list(limit=limit)]

    def result_matrix(self, *, limit: int = 50) -> dict:
        """完了済みキャンペーンを同じ列で比較できる公式指標行へ整形する。"""
        return build_campaign_results(
            self.campaigns,
            self.application,
            self.evaluation,
            limit=limit,
        )

    def detail(self, campaign_id: str) -> dict:
        campaign = self.get(campaign_id)
        entries = [self._entry_detail(item) for item in self.campaigns.list_entries(campaign_id)]
        statuses = {item["status"] for item in entries}
        if "NEEDS_ATTENTION" in statuses:
            status = "NEEDS_ATTENTION"
        elif entries and statuses == {"COMPLETED"}:
            status = "COMPLETED"
        else:
            status = "RUNNING"
        value = asdict(campaign)
        value.pop("request_key_hash")
        value.pop("model_keys")
        finalization = self.campaigns.get_finalization(campaign_id)
        return {
            **value,
            "status": status,
            "entries": entries,
            "finalization": None if finalization is None else asdict(finalization),
        }

    def retry_finalization(self, campaign_id: str) -> dict:
        self.get(campaign_id)
        self.campaigns.retry_finalization(campaign_id)
        return self.detail(campaign_id)

    def _entry_detail(self, entry: CampaignEntry) -> dict:
        run = self.application.get_run(entry.run_id)
        job = self.conformance.get(entry.conformance_job_id)
        needs_attention = run.status in {"FAILED", "CANCELLED"} or job.status == "FAILED"
        complete = run.status in {"SUCCEEDED", "PARTIAL"} and job.status == "SUCCEEDED"
        status = "NEEDS_ATTENTION" if needs_attention else "COMPLETED" if complete else "RUNNING"
        return {
            **asdict(entry),
            "status": status,
            "run_status": run.status,
            "conformance_status": job.status,
            "conformance_id": job.conformance_id,
            "error_code": job.error_code,
            "error_message": job.error_message,
        }
