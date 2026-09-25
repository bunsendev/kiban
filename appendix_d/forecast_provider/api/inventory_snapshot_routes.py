"""Phase 3S-4 inventory snapshot API。"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request, status

from ..inventory_foundation import InventoryReadError, InventorySnapshotReadService
from .error_responses import error_response
from .inventory_snapshot_schemas import (
    InventorySnapshotDecisionCreate,
    InventorySnapshotJobCreate,
)
from .security import Permission, Principal


def _call(request: Request, function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except InventoryReadError as exc:
        return error_response(
            request, exc.status_code, exc.message, code=exc.code
        )


def install_inventory_snapshot_routes(
    app: FastAPI, authorize, service: InventorySnapshotReadService
) -> None:
    read = authorize.require(Permission.READ)
    analyze = authorize.require(Permission.ANALYZE)
    approve = authorize.require(Permission.APPROVE)

    @app.post("/api/inventory-snapshot-jobs", status_code=status.HTTP_202_ACCEPTED)
    def register_job(
        payload: InventorySnapshotJobCreate,
        request: Request,
        principal: Annotated[Principal, Depends(analyze)],
    ):
        request.state.audit_operation = "INVENTORY_SNAPSHOT_JOB_REGISTERED"
        return _call(
            request,
            service.register_job,
            source_reference=payload.source_reference,
            source_sha256=payload.source_sha256.lower(),
            mapping_version=payload.mapping_version,
            known_at=payload.known_at,
            requested_by=principal.subject,
        )

    @app.get("/api/inventory-snapshot-jobs/{job_id}")
    def get_job(
        job_id: str,
        request: Request,
        _principal: Annotated[Principal, Depends(read)],
    ):
        return _call(request, service.get_job, job_id)

    @app.get("/api/inventory-snapshot-jobs/{job_id}/quarantine-summary")
    def quarantine_summary(
        job_id: str,
        request: Request,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        return _call(request, service.quarantine_summary, job_id)

    @app.get("/api/inventory-snapshot-jobs/{job_id}/reconciliation")
    def reconciliation(
        job_id: str,
        request: Request,
        _principal: Annotated[Principal, Depends(analyze)],
    ):
        return _call(request, service.reconciliation, job_id)

    @app.get("/api/inventory-snapshots")
    def list_snapshots(
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
        decision_status: Literal["APPROVED", "REJECTED", "UNREVIEWED"] | None = None,
    ):
        return service.list_snapshots(
            limit=limit, offset=offset, decision_status=decision_status
        )

    @app.get("/api/inventory-snapshots/approved/as-of")
    def approved_as_of(
        calculation_at: datetime,
        request: Request,
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
        offset: Annotated[int, Query(ge=0)] = 0,
        jan: Annotated[str | None, Query(pattern=r"^[0-9]{8}([0-9]{5})?$")] = None,
        location_id: str | None = None,
        location_type: Literal["FACTORY", "WAREHOUSE"] | None = None,
    ):
        request.state.audit_operation = "INVENTORY_APPROVED_AS_OF_READ"
        return _call(
            request,
            service.approved_as_of,
            calculation_at,
            limit=limit,
            offset=offset,
            jan=jan,
            location_id=location_id,
            location_type=location_type,
        )

    @app.get("/api/inventory-snapshots/{snapshot_id}")
    def get_snapshot(
        snapshot_id: str,
        request: Request,
        _principal: Annotated[Principal, Depends(read)],
    ):
        return _call(request, service.get_snapshot, snapshot_id)

    @app.get("/api/inventory-snapshots/{snapshot_id}/decisions")
    def decision_history(
        snapshot_id: str,
        request: Request,
        _principal: Annotated[Principal, Depends(read)],
    ):
        return _call(request, service.decision_history, snapshot_id)

    @app.post(
        "/api/inventory-snapshots/{snapshot_id}/decisions",
        status_code=status.HTTP_201_CREATED,
    )
    def append_decision(
        snapshot_id: str,
        payload: InventorySnapshotDecisionCreate,
        request: Request,
        principal: Annotated[Principal, Depends(approve)],
    ):
        request.state.audit_operation = "INVENTORY_SNAPSHOT_DECISION_APPENDED"
        return _call(
            request,
            service.append_decision,
            snapshot_id=snapshot_id,
            decision=payload.decision,
            reason=payload.reason,
            expected_revision=payload.expected_revision,
            decided_by=principal.subject,
        )

    @app.get("/api/inventory-snapshots/{snapshot_id}/fefo")
    def approved_fefo(
        snapshot_id: str,
        request: Request,
        _principal: Annotated[Principal, Depends(read)],
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
        offset: Annotated[int, Query(ge=0)] = 0,
        jan: Annotated[str | None, Query(pattern=r"^[0-9]{8}([0-9]{5})?$")] = None,
        location_id: str | None = None,
        location_type: Literal["FACTORY", "WAREHOUSE"] | None = None,
    ):
        request.state.audit_operation = "INVENTORY_APPROVED_FEFO_READ"
        return _call(
            request,
            service.approved_fefo,
            snapshot_id,
            limit=limit,
            offset=offset,
            jan=jan,
            location_id=location_id,
            location_type=location_type,
        )
