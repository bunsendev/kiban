"""Phase 3S-4 inventory APIとPhase 3Tが共有するread/application service。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal

from .contracts import SnapshotDecisionType
from .job_store import InventoryDecisionConflict
from .service import create_inventory_snapshot_job


class InventoryReadError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(code)


def _iso(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _public_row(row: dict) -> dict:
    return {key: _iso(value) for key, value in row.items()}


def _decision_output(row: dict) -> dict:
    output = _public_row(row)
    output["subject"] = output["decided_by"]
    output["created_at"] = output["decided_at"]
    return output


class InventorySnapshotReadService:
    """永続化層を直接共有し、HTTP自己呼出しを行わない正式read境界。"""

    def __init__(self, store, *, clock=lambda: datetime.now(UTC)):
        self.store = store
        self.clock = clock

    def register_job(
        self,
        *,
        source_reference: str,
        source_sha256: str,
        mapping_version: str,
        known_at: datetime,
        requested_by: str,
    ) -> dict:
        if self.store.get_mapping(mapping_version) is None:
            raise InventoryReadError(
                "INVENTORY_MAPPING_NOT_FOUND", "mapping versionが見つかりません", 404
            )
        try:
            value = create_inventory_snapshot_job(
                source_reference=source_reference,
                source_sha256=source_sha256,
                mapping_version=mapping_version,
                requested_by=requested_by,
                known_at=known_at,
                requested_at=self.clock(),
            )
        except ValueError as exc:
            raise InventoryReadError(
                "INVENTORY_JOB_REQUEST_INVALID", "job登録内容を確認してください", 422
            ) from exc
        stored = self.store.put_job(value)
        return self._job_output(stored)

    def get_job(self, job_id: str) -> dict:
        value = self.store.get_job(job_id)
        if value is None:
            raise InventoryReadError(
                "INVENTORY_JOB_NOT_FOUND", "inventory snapshot jobが見つかりません", 404
            )
        output = self._job_output(value)
        snapshots = self.store.list_snapshots(job_id)
        reconciliation = self.store.get_reconciliation(job_id)
        output.update(
            snapshot_id=None if not snapshots else snapshots[-1]["snapshot_id"],
            quarantine_count=value.quarantined_row_count,
            reconciliation_status=(
                None
                if reconciliation is None
                else "MATCHED"
                if bool(reconciliation["reconciled"])
                else "MISMATCHED"
            ),
        )
        return output

    @staticmethod
    def _job_output(value) -> dict:
        output = asdict(value)
        output["source_kind"] = value.source_kind.value
        output["status"] = value.status.value
        for key in (
            "known_at",
            "requested_at",
            "started_at",
            "finished_at",
            "leased_until",
            "last_heartbeat_at",
        ):
            output[key] = _iso(output[key])
        output["completed_at"] = output.pop("finished_at")
        for secret in (
            "source_reference",
            "worker_id",
            "lease_token",
            "leased_until",
            "last_heartbeat_at",
        ):
            output.pop(secret, None)
        return output

    def quarantine_summary(self, job_id: str) -> dict:
        self.get_job(job_id)
        items = self.store.quarantine_summary(job_id)
        return {
            "job_id": job_id,
            "total": sum(item["row_count"] for item in items),
            "items": items,
        }

    def reconciliation(self, job_id: str) -> dict:
        self.get_job(job_id)
        row = self.store.get_reconciliation(job_id)
        if row is None:
            raise InventoryReadError(
                "INVENTORY_RECONCILIATION_NOT_FOUND",
                "照合結果はまだ生成されていません",
                409,
            )
        source = Decimal(str(row["source_quantity_cases"]))
        normalized = Decimal(str(row["normalized_quantity_cases"]))
        return {
            "job_id": job_id,
            "source_quantity": str(source),
            "normalized_quantity": str(normalized),
            "difference": str(normalized - source),
            "matched": bool(row["reconciled"]),
            "normalized_unit": "CASE",
            "created_at": _iso(row["created_at"]),
        }

    def list_snapshots(
        self, *, limit: int, offset: int, decision_status: str | None
    ) -> dict:
        total, rows = self.store.list_snapshots_page(
            limit=limit, offset=offset, decision_status=decision_status
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [_public_row(row) for row in rows],
        }

    def get_snapshot(self, snapshot_id: str) -> dict:
        row = self.store.get_snapshot(snapshot_id)
        if row is None:
            raise InventoryReadError(
                "INVENTORY_SNAPSHOT_NOT_FOUND", "inventory snapshotが見つかりません", 404
            )
        latest = self.store.get_latest_snapshot_decision(snapshot_id)
        output = _public_row(row)
        output["current_decision"] = None if latest is None else _decision_output(latest)
        return output

    def decision_history(self, snapshot_id: str) -> dict:
        self.get_snapshot(snapshot_id)
        items = self.store.list_snapshot_decisions(snapshot_id)
        return {
            "snapshot_id": snapshot_id,
            "items": [_decision_output(row) for row in items],
        }

    def append_decision(
        self,
        *,
        snapshot_id: str,
        decision: str,
        reason: str | None,
        expected_revision: int,
        decided_by: str,
    ) -> dict:
        snapshot = self.get_snapshot(snapshot_id)
        try:
            result = self.store.append_snapshot_decision(
                job_id=snapshot["job_id"],
                snapshot_id=snapshot_id,
                decision=SnapshotDecisionType(decision),
                decided_by=decided_by,
                reason=(reason or "").strip(),
                decided_at=self.clock(),
                expected_revision=expected_revision,
            )
        except InventoryDecisionConflict as exc:
            raise InventoryReadError(
                "INVENTORY_DECISION_CONFLICT",
                "承認状態が更新されています。再読込してください",
                409,
            ) from exc
        except ValueError as exc:
            raise InventoryReadError(
                "INVENTORY_DECISION_INVALID", "承認入力を確認してください", 422
            ) from exc
        return _decision_output(result)

    def approved_fefo(
        self,
        snapshot_id: str,
        *,
        limit: int,
        offset: int,
        jan: str | None = None,
        location_id: str | None = None,
        location_type: str | None = None,
    ) -> dict:
        snapshot = self.get_snapshot(snapshot_id)
        latest = snapshot["current_decision"]
        if latest is None or latest["decision"] != "APPROVED":
            raise InventoryReadError(
                "INVENTORY_SNAPSHOT_NOT_APPROVED",
                "承認済みsnapshotだけを正式入力として取得できます",
                409,
            )
        return self._fefo_page(
            snapshot,
            limit=limit,
            offset=offset,
            jan=jan,
            location_id=location_id,
            location_type=location_type,
        )

    def approved_as_of(
        self,
        calculation_at: datetime,
        *,
        limit: int,
        offset: int,
        jan: str | None = None,
        location_id: str | None = None,
        location_type: str | None = None,
    ) -> dict:
        if calculation_at.tzinfo is None or calculation_at.utcoffset() is None:
            raise InventoryReadError(
                "INVENTORY_CALCULATION_AT_INVALID",
                "calculation_atはtimezone付き日時です",
                422,
            )
        row = self.store.find_approved_snapshot_as_of(
            calculation_at,
            jan=jan,
            location_id=location_id,
            location_type=location_type,
        )
        if row is None:
            raise InventoryReadError(
                "INVENTORY_APPROVED_SNAPSHOT_NOT_FOUND",
                "計算時点で利用可能な承認済みsnapshotがありません",
                404,
            )
        snapshot = _public_row(row)
        snapshot["calculation_at"] = _iso(calculation_at)
        return self._fefo_page(
            snapshot,
            limit=limit,
            offset=offset,
            jan=jan,
            location_id=location_id,
            location_type=location_type,
        )

    def _fefo_page(self, snapshot: dict, **filters) -> dict:
        total, rows = self.store.list_expiry_buckets_page(
            snapshot["snapshot_id"], **filters
        )
        snapshot_at = datetime.fromisoformat(
            str(snapshot["snapshot_at"]).replace("Z", "+00:00")
        ).date()
        items = []
        for row in rows:
            item = _public_row(row)
            item["expired_at_snapshot"] = date.fromisoformat(str(row["expiry_date"])) < snapshot_at
            items.append(item)
        return {
            "snapshot": snapshot,
            "total": total,
            "limit": filters["limit"],
            "offset": filters["offset"],
            "items": items,
        }
