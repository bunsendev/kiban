import csv
import io
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Response

from ..operation_events import make_operation_event
from .operation_event_schemas import OperationEventCreate
from .security import Permission, Principal


def install_operation_event_routes(app, authorize, store, retention_days: int = 180) -> None:
    if store is None:
        return
    if not 1 <= retention_days <= 3_650:
        raise ValueError("操作logの保持日数は1〜3650日です")
    read = authorize.require(Permission.READ)
    approve = authorize.require(Permission.APPROVE)
    export = authorize.require(Permission.EXPORT)
    last_purge = 0.0

    @app.post("/api/operation-events", status_code=201)
    def create_operation_event(
        request: OperationEventCreate,
        principal: Annotated[Principal, Depends(read)],
    ):
        nonlocal last_purge
        try:
            now = datetime.now(UTC)
            if time.monotonic() - last_purge >= 3_600:
                store.purge_before(now - timedelta(days=retention_days))
                last_purge = time.monotonic()
            value = make_operation_event(request.model_dump(mode="python"), principal.subject, now)
            return asdict(store.append(value))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/operation-events")
    def list_operation_events(
        _principal: Annotated[Principal, Depends(approve)],
        days: Annotated[int, Query(ge=1, le=365)] = 30,
        screen: Annotated[str | None, Query(max_length=40)] = None,
        event_name: Annotated[str | None, Query(max_length=50)] = None,
        limit: Annotated[int, Query(ge=1, le=1_000)] = 200,
    ):
        since = datetime.now(UTC) - timedelta(days=days)
        return [
            asdict(value)
            for value in store.list_events(
                since=since, screen=screen, event_name=event_name, limit=limit
            )
        ]

    @app.get("/api/operation-events/summary")
    def summarize_operation_events(
        _principal: Annotated[Principal, Depends(approve)],
        days: Annotated[int, Query(ge=1, le=365)] = 30,
    ):
        return store.summarize(datetime.now(UTC) - timedelta(days=days))

    @app.get("/api/operation-events/export.csv")
    def export_operation_events(
        _principal: Annotated[Principal, Depends(export)],
        days: Annotated[int, Query(ge=1, le=365)] = 30,
    ):
        values = store.list_events(
            since=datetime.now(UTC) - timedelta(days=days), limit=100_000
        )
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(
            [
                "event_id",
                "flow_session_id",
                "subject",
                "screen",
                "event_name",
                "step",
                "sequence",
                "outcome",
                "elapsed_ms",
                "source_mode",
                "file_kind",
                "file_size_bucket",
                "source_count_bucket",
                "column_count_bucket",
                "source_age_bucket",
                "stage_name",
                "mapping_match",
                "retry_count",
                "selection_count",
                "flow_version",
                "viewport_bucket",
                "work_item_id",
                "result_outcome",
                "error_kind",
                "occurred_at",
                "received_at",
            ]
        )
        for value in values:
            writer.writerow(
                [
                    value.event_id,
                    value.flow_session_id,
                    value.subject,
                    value.screen,
                    value.event_name,
                    value.step,
                    value.sequence,
                    value.outcome,
                    value.elapsed_ms if value.elapsed_ms is not None else "",
                    value.metadata.get("source_mode", ""),
                    value.metadata.get("file_kind", ""),
                    value.metadata.get("file_size_bucket", ""),
                    value.metadata.get("source_count_bucket", ""),
                    value.metadata.get("column_count_bucket", ""),
                    value.metadata.get("source_age_bucket", ""),
                    value.metadata.get("stage_name", ""),
                    value.metadata.get("mapping_match", ""),
                    value.metadata.get("retry_count", ""),
                    value.metadata.get("selection_count", ""),
                    value.metadata.get("flow_version", ""),
                    value.metadata.get("viewport_bucket", ""),
                    value.metadata.get("work_item_id", ""),
                    value.metadata.get("result_outcome", ""),
                    value.metadata.get("error_kind", ""),
                    value.occurred_at.isoformat(),
                    value.received_at.isoformat(),
                ]
            )
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="operation-events.csv"'},
        )
