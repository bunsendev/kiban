"""inventory snapshot jobを1件ずつ処理する独立Worker core。"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import UTC, datetime

from .csv_adapter import InventoryCsvContractError
from .job_contracts import InventorySnapshotJobErrorCode
from .references import InventoryReferenceResolver
from .service import InventorySnapshotProcessingError, InventorySnapshotService
from .sources import InventorySourceReader, InventorySourceReadError


class InventorySnapshotWorker:
    def __init__(
        self,
        store,
        source_reader: InventorySourceReader,
        *,
        resolver_factory: Callable = InventoryReferenceResolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.source_reader = source_reader
        self.resolver_factory = resolver_factory
        self.clock = clock or (lambda: datetime.now(UTC))
        self.service = InventorySnapshotService()

    def run_once(self, worker_id: str, *, lease_seconds: int = 60):
        lease = self.store.claim_next_job(
            worker_id,
            lease_seconds=lease_seconds,
            now=self.clock(),
        )
        if lease is None:
            return None
        try:
            content = self.source_reader.read(lease.job.source_reference)
            lease = self.store.heartbeat(
                lease,
                lease_seconds=lease_seconds,
                now=self.clock(),
            )
            mapping = self.store.get_mapping(lease.job.mapping_version)
            if mapping is None:
                raise InventorySnapshotProcessingError(
                    InventorySnapshotJobErrorCode.MAPPING_NOT_FOUND
                )
            snapshot_time_policy = (
                self.store.get_snapshot_time_policy(mapping.snapshot_at_policy_version)
                if mapping.snapshot_at_policy_version is not None
                else None
            )
            locations = self.store.list_locations(mapping.location_master_version)
            product_mappings = (
                self.store.list_product_mappings(mapping.product_mapping_version)
                if mapping.product_mapping_version is not None
                else ()
            )
            resolver = self._resolver(mapping, locations, product_mappings)
            finalization = self.service.prepare_finalization(
                lease,
                content,
                mapping,
                resolver,
                snapshot_time_policy=snapshot_time_policy,
                completed_at=self.clock(),
            )
            self.store.finalize_job(lease, finalization)
        except InventorySourceReadError as exc:
            self.store.fail_job(lease, exc.code, retryable=False, now=self.clock())
        except InventoryCsvContractError:
            self.store.fail_job(
                lease,
                InventorySnapshotJobErrorCode.CSV_CONTRACT_FAILED,
                retryable=False,
                now=self.clock(),
            )
        except InventorySnapshotProcessingError as exc:
            self.store.fail_job(lease, exc.code, retryable=False, now=self.clock())
        except Exception:
            self.store.fail_job(
                lease,
                InventorySnapshotJobErrorCode.INTERNAL_ERROR,
                retryable=True,
                now=self.clock(),
            )
        return self.store.get_job(lease.job.job_id)

    def _resolver(self, mapping, locations, product_mappings):
        """既存の2引数factoryを維持しつつ、正式商品mappingを標準factoryへ渡す。"""

        parameters = inspect.signature(self.resolver_factory).parameters.values()
        accepts_product_mappings = any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL for parameter in parameters
        ) or sum(
            parameter.kind
            in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
            for parameter in parameters
        ) >= 3
        if accepts_product_mappings:
            return self.resolver_factory(mapping, locations, product_mappings)
        return self.resolver_factory(mapping, locations)
