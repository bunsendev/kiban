"""失敗記録の型と出力先。DBやrunnerへ実行時依存しない。"""

from __future__ import annotations

import traceback as traceback_module
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Protocol

from .errors import ContractViolationError, ProviderError

if TYPE_CHECKING:
    from .run_context import RunContext


@dataclass(frozen=True)
class FailureRecord:
    run_id: str
    experiment_id: str
    origin_date: date | None
    cutoff_at: datetime
    error: str
    exception_type: str
    retryable: bool
    message: str
    traceback: str | None

    def as_legacy_error(self) -> dict:
        """v2.9 errorsのキー・日付表現を維持する。fit失敗のoriginはNone。"""
        return {
            "origin_date": (
                str(datetime.combine(self.origin_date, time.min)) if self.origin_date else None
            ),
            "error": self.error,
            "exception_type": self.exception_type,
            "retryable": self.retryable,
            "message": self.message,
            "traceback": self.traceback,
        }


class FailureSink(Protocol):
    def record(self, failure: FailureRecord) -> None:
        """失敗を記録する。失敗した場合は例外を送出する。"""
        ...


@dataclass
class InMemoryFailureSink:
    records: list[FailureRecord] = field(default_factory=list)

    def record(self, failure: FailureRecord) -> None:
        self.records.append(failure)


class FailureSinkError(RuntimeError):
    """記録先の障害。元の失敗を保持し、予測失敗へ再分類せず停止する。"""

    def __init__(self, record: FailureRecord) -> None:
        self.record = record
        super().__init__(f"failure sinkへの記録に失敗しました: {record.error}")


def record_failure(
    errors: list[dict], context: RunContext, origin: date | None, exc: Exception
) -> None:
    if isinstance(exc, (ContractViolationError, FailureSinkError)):
        raise exc
    classified = isinstance(exc, ProviderError)
    record = FailureRecord(
        run_id=context.run_id,
        experiment_id=context.experiment_id,
        origin_date=origin,
        cutoff_at=context.cutoff_at,
        error=type(exc).__name__ if classified else "UNCLASSIFIED_ERROR",
        exception_type=type(exc).__name__,
        retryable=bool(exc.retryable) if classified else False,
        message=str(exc),
        traceback=None
        if classified
        else "".join(traceback_module.format_exception(type(exc), exc, exc.__traceback__)),
    )
    errors.append(record.as_legacy_error())
    if context.failure_sink is not None:
        try:
            context.failure_sink.record(record)
        except Exception as sink_error:
            raise FailureSinkError(record) from sink_error
