"""Read verified completed forecasts independently of the current intake gate."""

import re

from .formal_forecast_pipeline import FormalForecastError
from .production_handoff import ProductionHandoffError


class SavedForecasts:
    def __init__(self, forecast, production):
        self.forecast = forecast
        self.production = production

    def manifest(self, reference):
        if not re.fullmatch(r"portable-daily-[0-9a-f]{64}", reference):
            raise ValueError("保存済み予測が見つかりません")
        try:
            value = self.forecast._verified_result(self.forecast.root / reference / "manifest.json")
            if value.get("build_id") != reference or not isinstance(value.get("created_at"), str):
                raise ValueError("保存済み予測の識別子・保存日時が一致しません")
            return value
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
            raise ValueError("保存済み予測の整合性を確認できません") from exc

    def filter_rows(self, kind, reference, rows, warehouse):
        if not warehouse:
            return rows
        if kind != "production":
            raise ValueError("この結果は倉庫別表示に対応していません")
        value = self.manifest(reference)
        ids = {
            s["unique_id"]
            for s in value["series"]
            if s["source_center"] == warehouse and s["forecast_eligible"]
        }
        selected = [r for r in rows if r["unique_id"] in ids]
        if not selected:
            raise ValueError("この保存版には指定倉庫の完成した予測がありません")
        return selected

    def list(self, warehouse="", offset=0, limit=50):
        entries = []
        unavailable = 0
        for path in self.forecast.root.glob("portable-daily-*/manifest.json"):
            try:
                value = self.manifest(path.parent.name)
                if not value.get("eligible_series_count"):
                    continue
                production = self.production.current(value["build_id"]).get("handoff") or {}
                if production.get("run_status") != "SUCCEEDED":
                    continue
                points = production.get("point_predictions", [])
                windows = {w["source_center"]: w for w in value["center_windows"]}
                point_ids = {r["unique_id"] for r in points}
                for center in sorted(
                    {
                        s["source_center"]
                        for s in value["series"]
                        if s["forecast_eligible"] and s["unique_id"] in point_ids
                    }
                ):
                    ids = {s["unique_id"] for s in value["series"] if s["source_center"] == center}
                    rows = [r for r in points if r["unique_id"] in ids]
                    window = windows[center]
                    dates = sorted(str(r["target_date"])[:10] for r in rows)
                    entries.append(
                        {
                            "kind": "production",
                            "reference": value["build_id"],
                            "warehouse": center,
                            "created_at": value["created_at"],
                            "inventory_date": window.get("inventory_snapshot_date"),
                            "train_end": window["train_end"],
                            "period": [dates[0], dates[-1]],
                            "series_count": len({r["unique_id"] for r in rows}),
                            "row_count": len(rows),
                        }
                    )
            except (
                ValueError,
                KeyError,
                TypeError,
                OSError,
                FormalForecastError,
                ProductionHandoffError,
            ):
                unavailable += 1
        entries.sort(key=lambda v: (v["created_at"], v["reference"], v["warehouse"]), reverse=True)
        warehouses = sorted({v["warehouse"] for v in entries})
        matches = [v for v in entries if not warehouse or v["warehouse"] == warehouse]
        return {
            "items": matches[offset : offset + limit],
            "warehouses": warehouses,
            "total": len(matches),
            "unavailable_count": unavailable,
        }
