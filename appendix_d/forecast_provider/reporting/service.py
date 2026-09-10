"""保存済み比較のCSV化と採用条件を結合するアプリケーションサービス。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..acceptance.contracts import AcceptanceStore
from ..catalog import CatalogStore
from ..catalog.files import verify_snapshot_file
from ..evaluation_registry.contracts import EvaluationRegistryStore
from .contracts import AdoptionRecord, ExportRecord, ReportingStore
from .domain import export_identity, make_adoption, make_export_record
from .export import publish_csv, render_comparison_csv


class ReportingNotFound(KeyError):
    pass


class ReportingConflict(ValueError):
    pass


class ReportingService:
    def __init__(
        self,
        evaluation: EvaluationRegistryStore,
        catalog: CatalogStore,
        acceptance: AcceptanceStore,
        store: ReportingStore,
        output_root: Path,
        snapshot_root: Path | None = None,
    ) -> None:
        self.evaluation = evaluation
        self.catalog = catalog
        self.acceptance = acceptance
        self.store = store
        self.output_root = output_root
        self.snapshot_root = snapshot_root

    def create_export(self, comparison_id: str, request: dict) -> ExportRecord:
        comparison = self._comparison(comparison_id)
        evaluations = self.evaluation.list_run_evaluations(comparison_id)
        if request["baseline_run_id"] not in {item.run_id for item in evaluations}:
            raise ReportingConflict("baseline runが比較結果に含まれません")
        snapshot = self._snapshot(comparison.definition["truth_snapshot_id"])
        try:
            verify_snapshot_file(
                snapshot.manifest["data_uri"],
                snapshot.manifest["data_sha256"],
                self.snapshot_root,
            )
        except (OSError, ValueError, KeyError) as exc:
            raise ReportingConflict("比較snapshotの検証に失敗しました") from exc
        definition = {
            "comparison_id": comparison_id,
            "export_version": request["export_version"],
            "baseline_run_id": request["baseline_run_id"],
            "requested_by": request["requested_by"],
        }
        export_id, _, _ = export_identity(definition)
        payload = render_comparison_csv(
            export_id,
            request["export_version"],
            comparison,
            evaluations,
            request["baseline_run_id"],
            request["requested_by"],
            snapshot,
        )
        uri, checksum = publish_csv(payload, self.output_root)
        record = make_export_record(definition, uri, checksum, len(evaluations))
        try:
            return self.store.put_export(record)
        except (OSError, ValueError) as exc:
            raise ReportingConflict(str(exc)) from exc

    def get_export(self, export_id: str) -> ExportRecord:
        value = self.store.get_export(export_id)
        if value is None:
            raise ReportingNotFound(export_id)
        return value

    def list_exports(self, comparison_id: str | None = None) -> list[ExportRecord]:
        return self.store.list_exports(comparison_id)

    def export_path(self, export_id: str) -> tuple[ExportRecord, Path]:
        record = self.get_export(export_id)
        try:
            path = verify_snapshot_file(
                record.output_uri, record.output_sha256, self.output_root
            )
        except (OSError, ValueError) as exc:
            raise ReportingConflict(str(exc)) from exc
        return record, path

    def create_adoption(self, request: dict) -> AdoptionRecord:
        value = make_adoption(request)
        comparison = self._comparison(value.comparison_id)
        snapshot = self._snapshot(comparison.definition["truth_snapshot_id"])
        if value.target["selection_version"] != snapshot.manifest["selection_version"]:
            raise ReportingConflict("採用対象と比較snapshotのselection versionが一致しません")
        if value.decision == "ADOPTED":
            self._validate_adoption(value, comparison.result, snapshot)
        try:
            return self.store.put_adoption(value)
        except ValueError as exc:
            raise ReportingConflict(str(exc)) from exc

    def _validate_adoption(self, value: AdoptionRecord, result: dict, snapshot) -> None:
        if not result["official_ranking_ready"]:
            raise ReportingConflict("正式ランキングが成立した比較だけを採用できます")
        official = set(result["official_runs"])
        if value.selected_run_id not in official or value.fallback_run_id not in official:
            raise ReportingConflict("採用runとfallback runは正式比較対象から選びます")
        case = self.acceptance.get_case(value.acceptance_case_id)
        if case is None:
            raise ReportingNotFound(value.acceptance_case_id)
        if (
            case.status != "SUCCEEDED"
            or case.outcome != "PASSED"
            or case.definition["data_kind"] != "REAL"
        ):
            raise ReportingConflict("合格済み実データ受入caseだけを採用に使用できます")
        decisions = self.acceptance.list_decisions(case.case_id)
        if not decisions or decisions[-1].decision != "APPROVED":
            raise ReportingConflict("受入caseの最新業務判断がAPPROVEDではありません")
        build_id = snapshot.manifest.get("provenance", {}).get("daily_build_id")
        if not build_id or build_id != case.definition["daily_build_id"]:
            raise ReportingConflict("比較snapshotと受入caseの日次buildが一致しません")
        expected = set(case.definition["expected_product_ids"])
        products = set(value.target["canonical_product_ids"])
        if not products.issubset(expected):
            raise ReportingConflict("採用品目が受入caseの対象外です")
        actual_products, actual_centers = self._snapshot_dimensions(snapshot)
        if not products.issubset(actual_products):
            raise ReportingConflict("採用品目が比較snapshotに含まれません")
        if not set(value.target["center_ids"]).issubset(actual_centers):
            raise ReportingConflict("採用centerが比較snapshotに含まれません")

    def get_adoption(self, adoption_id: str) -> AdoptionRecord:
        value = self.store.get_adoption(adoption_id)
        if value is None:
            raise ReportingNotFound(adoption_id)
        return value

    def list_adoptions(self, comparison_id: str | None = None) -> list[AdoptionRecord]:
        return self.store.list_adoptions(comparison_id)

    def adoption_context(self, comparison_id: str) -> dict:
        comparison = self._comparison(comparison_id)
        snapshot = self._snapshot(comparison.definition["truth_snapshot_id"])
        products, centers = self._snapshot_dimensions(snapshot)
        daily_build_id = snapshot.manifest.get("provenance", {}).get("daily_build_id")
        official = set(comparison.result["official_runs"])
        evaluations = self.evaluation.list_run_evaluations(comparison_id)
        return {
            "comparison_id": comparison_id,
            "truth_snapshot_id": snapshot.snapshot_id,
            "daily_build_id": daily_build_id,
            "selection_version": snapshot.manifest["selection_version"],
            "canonical_product_ids": sorted(products),
            "center_ids": sorted(centers),
            "official_ranking_ready": comparison.result["official_ranking_ready"],
            "run_evaluations": [
                {
                    "run_id": item.run_id,
                    "provider_id": item.provider_id,
                    "model_name": item.model_name,
                    "official_included": item.run_id in official,
                    "run_success_rate": item.score.get("run_success_rate"),
                    "common_wape_pct": (item.score.get("common_metrics") or {}).get(
                        "wape_pct"
                    ),
                }
                for item in evaluations
            ],
            "acceptance_cases": self._acceptance_context(daily_build_id),
        }

    def _acceptance_context(self, daily_build_id: str | None) -> list[dict]:
        result = []
        for case in self.acceptance.list_cases():
            if case.definition["daily_build_id"] != daily_build_id:
                continue
            decisions = self.acceptance.list_decisions(case.case_id)
            latest = None if not decisions else decisions[-1]
            result.append(
                {
                    "case_id": case.case_id,
                    "acceptance_version": case.definition["acceptance_version"],
                    "data_kind": case.definition["data_kind"],
                    "status": case.status,
                    "outcome": case.outcome,
                    "latest_decision": None if latest is None else latest.decision,
                    "eligible": bool(
                        case.status == "SUCCEEDED"
                        and case.outcome == "PASSED"
                        and case.definition["data_kind"] == "REAL"
                        and latest is not None
                        and latest.decision == "APPROVED"
                    ),
                }
            )
        return result

    def _comparison(self, comparison_id: str):
        value = self.evaluation.get_comparison(comparison_id)
        if value is None:
            raise ReportingNotFound(comparison_id)
        return value

    def _snapshot(self, snapshot_id: str):
        value = self.catalog.get_snapshot(snapshot_id)
        if value is None:
            raise ReportingNotFound(snapshot_id)
        return value

    def _snapshot_dimensions(self, snapshot) -> tuple[set[str], set[str]]:
        try:
            path = verify_snapshot_file(
                snapshot.manifest["data_uri"],
                snapshot.manifest["data_sha256"],
                self.snapshot_root,
            )
            frame = pd.read_csv(path, usecols=["canonical_product_id", "center_id"])
        except (OSError, ValueError, KeyError) as exc:
            raise ReportingConflict("採用には商品・center付きの検証済みsnapshotが必要です") from exc
        products = {str(value) for value in frame["canonical_product_id"].dropna()}
        centers = {str(value) for value in frame["center_id"].dropna()}
        return products, centers
