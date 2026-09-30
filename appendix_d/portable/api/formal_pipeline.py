"""Run verified Portable inventory through the existing Unified Inbox and Worker."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from forecast_provider.field_pilot.formal_inventory import FormalInventorySubmission
from forecast_provider.field_pilot.inbox_ledger import InboxLedger
from forecast_provider.field_pilot.inbox_processor import InboxProcessor
from forecast_provider.inventory_foundation import (
    DirectoryInventorySourceReader,
    InventorySnapshotReadService,
    InventorySnapshotWorker,
    SqliteInventoryFoundationStore,
)
from forecast_provider.pilot_scope import SqlitePilotScopeStore

from .formal_pipeline_contracts import (
    FormalPipelineError,
    canonical_json,
    eligible_products,
    pipeline_identity,
    prepare_pipeline,
    sha256,
)


class PortableFormalPipeline:
    def __init__(self, paths) -> None:
        self.paths = paths
        self.database = paths.state / "formal-pipeline.sqlite3"
        self.inventory_store = SqliteInventoryFoundationStore(self.database)
        self.scope_store = SqlitePilotScopeStore(self.database)
        self.inbox_root = paths.root / "Inbox"
        self.staged = self.inbox_root / "Staged"
        self.archive = self.inbox_root / "Archive"
        self.registrations = paths.formal_inventory / "Registrations"
        for path in (self.inbox_root, self.staged, self.archive, self.registrations):
            path.mkdir(parents=True, exist_ok=True)

    def view(self, handoff_id: str) -> dict:
        handoff, package_dir = self._handoff(handoff_id)
        registrations = []
        for path in self.registrations.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if item.get("handoff_id") == handoff_id:
                registrations.append(item)
        registrations.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        latest = self.registration_view(registrations[0]) if registrations else None
        return {
            "handoff_id": handoff_id,
            "minimum_products_per_location": 10,
            "maximum_products_per_location": 20,
            "locations": eligible_products(handoff, package_dir),
            "latest": latest,
        }

    def register(self, handoff_id: str, payload: dict) -> dict:
        handoff, package_dir = self._handoff(handoff_id)
        registration_id, approved = pipeline_identity(handoff, payload)
        target = self.registrations / f"{registration_id}.json"
        if target.is_file():
            return self.registration_view(json.loads(target.read_text(encoding="utf-8")))
        created_at = datetime.now(UTC)
        prepared = prepare_pipeline(
            handoff, package_dir, approved, created_at=created_at,
            inventory_store=self.inventory_store, scope_store=self.scope_store,
        )
        self._stage(registration_id, prepared.files, created_at)
        ledger = InboxLedger(self.inbox_root / "inbox.sqlite3")
        submission = FormalInventorySubmission(
            self.inventory_store, self.scope_store, self.archive,
        )
        InboxProcessor(
            self.inbox_root, prepared.policy, ledger, validated_import=submission,
        ).scan()
        jobs = []
        for center, target_date in prepared.target_dates.items():
            location_code = next(
                item["location_code"] for item in handoff["locations"]
                if item["source_center"] == center
            )
            entries = ledger.recent_formal_jobs(prepared.policy.version, target_date, limit=100)
            entry = next(
                (item for item in entries if item["location_id"] == location_code), None
            )
            if entry is None:
                raise FormalPipelineError("Unified Inboxへ正式在庫ジョブを登録できませんでした")
            jobs.append({"source_center": center, "job_id": entry["job_id"]})
        worker = InventorySnapshotWorker(
            self.inventory_store, DirectoryInventorySourceReader(self.archive),
            pilot_scope_store=self.scope_store,
        )
        for _item in jobs:
            worker.run_once("PORTABLE_FORMAL_PIPELINE")
        registration = {
            "format": "portable-formal-pipeline-registration-v1",
            "registration_id": registration_id,
            "handoff_id": handoff_id,
            "policy_version": prepared.policy.version,
            "mapping_version": prepared.mapping.mapping_version,
            "location_master_version": prepared.location_version.location_master_version,
            "approved_by": approved["actor"],
            "approval_reason": approved["reason"],
            "created_at": created_at.isoformat(),
            "jobs": jobs,
            "notice": (
                "Unified Inboxと正式在庫Workerで検証しました。"
                "明示承認後だけ正式Snapshotになります。"
            ),
        }
        self._atomic_json(target, registration)
        return self.registration_view(registration)

    def approve(self, registration_id: str, job_id: str, payload: dict) -> dict:
        registration = self._registration(registration_id)
        if job_id not in {item["job_id"] for item in registration["jobs"]}:
            raise FormalPipelineError("対象の正式在庫ジョブが見つかりません")
        actor = str(payload.get("actor") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        revision = payload.get("expected_revision", 0)
        if not actor or not reason or isinstance(revision, bool) or not isinstance(revision, int):
            raise FormalPipelineError("承認者、承認理由、現在版を確認してください")
        ledger = InboxLedger(self.inbox_root / "inbox.sqlite3")
        job = self.inventory_store.get_job(job_id)
        reconciliation = self.inventory_store.get_reconciliation(job_id)
        snapshots = self.inventory_store.list_snapshots(job_id)
        if (
            job is None or str(job.status) != "SUCCEEDED" or job.quarantined_row_count != 0
            or not ledger.is_latest_formal_job(job_id) or reconciliation is None
            or not reconciliation["reconciled"] or len(snapshots) != 1
        ):
            raise FormalPipelineError("数量照合済みの最新ジョブだけ承認できます")
        InventorySnapshotReadService(self.inventory_store).append_decision(
            snapshot_id=snapshots[0]["snapshot_id"], decision="APPROVED", reason=reason,
            expected_revision=revision, decided_by=actor,
        )
        return self.registration_view(registration)

    def get_registration(self, registration_id: str) -> dict:
        """Return the immutable registration for a following adapter."""

        return self._registration(registration_id)

    def get_handoff(self, handoff_id: str) -> dict:
        """Return the verified handoff manifest for a following adapter."""

        return self._handoff(handoff_id)[0]

    def registration_view(self, registration: dict) -> dict:
        jobs = []
        for item in registration["jobs"]:
            job = self.inventory_store.get_job(item["job_id"])
            reconciliation = self.inventory_store.get_reconciliation(item["job_id"])
            snapshots = self.inventory_store.list_snapshots(item["job_id"])
            snapshot_id = snapshots[0]["snapshot_id"] if len(snapshots) == 1 else None
            decision = (
                self.inventory_store.get_latest_snapshot_decision(snapshot_id)
                if snapshot_id else None
            )
            state = "MISSING" if job is None else str(job.status)
            if state == "SUCCEEDED":
                state = "APPROVED" if decision and decision["decision"] == "APPROVED" else (
                    "REJECTED" if decision and decision["decision"] == "REJECTED"
                    else "APPROVAL_REQUIRED"
                )
            jobs.append({
                **item, "status": state, "snapshot_id": snapshot_id,
                "accepted_row_count": None if job is None else job.accepted_row_count,
                "quarantined_row_count": None if job is None else job.quarantined_row_count,
                "reconciliation_matched": bool(reconciliation and reconciliation["reconciled"]),
                "source_quantity_cases": None if not reconciliation else str(
                    reconciliation["source_quantity_cases"]
                ),
                "normalized_quantity_cases": None if not reconciliation else str(
                    reconciliation["normalized_quantity_cases"]
                ),
                "decision_revision": 0 if not decision else decision["revision"],
            })
        status = (
            "APPROVED" if jobs and all(item["status"] == "APPROVED" for item in jobs)
            else "APPROVAL_REQUIRED" if jobs and all(
                item["status"] in {"APPROVAL_REQUIRED", "APPROVED"} for item in jobs
            )
            else "PROCESSING_OR_BLOCKED"
        )
        return {
            **registration, "jobs": jobs, "status": status,
            "forecast_update_status": (
                "WAITING_FOR_FORMAL_SHIPMENT_DAILY_BUILD"
                if status == "APPROVED" else "WAITING_FOR_INVENTORY_APPROVAL"
            ),
        }

    def _handoff(self, handoff_id: str) -> tuple[dict, Path]:
        if len(handoff_id) != 64 or any(value not in "0123456789abcdef" for value in handoff_id):
            raise FormalPipelineError("正式取込候補が見つかりません")
        package_dir = self.paths.formal_inventory / handoff_id
        manifest_path = package_dir / "manifest.json"
        try:
            content = manifest_path.read_bytes()
            handoff = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            raise FormalPipelineError("正式取込候補が見つかりません") from exc
        if handoff.get("handoff_id") != handoff_id:
            raise FormalPipelineError("正式取込候補の識別子が一致しません")
        return handoff, package_dir

    def _registration(self, registration_id: str) -> dict:
        if len(registration_id) != 64 or any(
            value not in "0123456789abcdef" for value in registration_id
        ):
            raise FormalPipelineError("正式取込登録が見つかりません")
        try:
            return json.loads(
                (self.registrations / f"{registration_id}.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise FormalPipelineError("正式取込登録が見つかりません") from exc

    def _stage(self, registration_id: str, files: dict[str, bytes], created_at: datetime) -> None:
        for filename, content in sorted(files.items()):
            stage_id = sha256(canonical_json({
                "registration_id": registration_id, "filename": filename,
            }))[:32]
            binary = self.staged / f"{stage_id}.bin"
            manifest = self.staged / f"{stage_id}.json"
            if manifest.exists() and binary.exists():
                continue
            temporary = binary.with_suffix(".tmp")
            temporary.write_bytes(content)
            os.replace(temporary, binary)
            self._atomic_json(manifest, {
                "original_name": filename, "sha256": sha256(content),
                "size_bytes": len(content), "received_at": created_at.isoformat(),
            })

    @staticmethod
    def _atomic_json(path: Path, value: dict) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(canonical_json(value))
        os.replace(temporary, path)
