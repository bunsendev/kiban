"""Shipment-only reference forecasts; never fabricate inventory or missing days."""

import hashlib
import json
from datetime import UTC, datetime

import pandas as pd

from .business_archive import atomic_json
from .data_quality import DataQuality
from .document_evidence import valid_jan
from .forecast import forecast
from .forecast_capabilities import missing_capability
from .product_exclusions import ProductExclusions


def demand_forecast(paths, analysis_id, value):
    mode = value.get("forecast_mode", "A")
    if mode not in {"A", "C"}:
        raise ValueError("推定補完（B）は今後対応です")
    quality = DataQuality(paths)
    check = quality.check(analysis_id)
    if value.get("check_id") and value["check_id"] != check["id"]:
        raise ValueError("データ・設定が変わりました。欠損一覧を再確認してください")
    if mode == "C" and (value.get("confirm_provisional") is not True
                        or value.get("check_id") != check["id"]):
        raise ValueError("最新の欠損一覧と暫定予測への同意が必要です")
    actor = str(value.get("actor") or "").strip()
    unit = str(value.get("unit") or "").strip()
    if (
        not actor
        or not unit
        or len(actor) > 100
        or len(unit) > 50
        or value.get("confirmed") is not True
    ):
        raise ValueError("確認者・原本数量の単位・出荷データ確認を入力してください")
    report = json.loads((paths.analysis / f"{analysis_id}.json").read_text(encoding="utf-8"))
    if not report.get("prepared_sha256"):
        raise ValueError("旧版の解析です。「以前の受付済み原本を履歴へ再集計」を実行してください")
    prepared = (paths.prepared / f"{analysis_id}.csv").read_bytes()
    if hashlib.sha256(prepared).hexdigest() != report["prepared_sha256"]:
        raise ValueError("出荷集計が変更されています。元の入力から再集計してください")
    if report["rows"]["quarantined"] or any(
        i["category"] in ("shipment", "file") for i in report.get("issues", [])
    ):
        raise ValueError("出荷CSVの不正・未確認行を先に解消してください")
    frame = pd.read_csv(paths.prepared / f"{analysis_id}.csv", dtype={"unique_id": "string"})
    if frame.empty:
        raise ValueError("確認できる出荷実績がありません")
    frame["ds"] = pd.to_datetime(frame["ds"], format="%Y-%m-%d")
    frame["y"] = pd.to_numeric(frame["y"])
    rules = ProductExclusions(paths)
    series, predictions = [], []
    excluded = 0
    for uid, group in frame.groupby("unique_id", sort=True):
        center, jan = str(uid).rsplit(":", 1)
        if len(jan) != 13 or not valid_jan(jan):
            raise ValueError("出荷CSVのJANチェック桁を確認してください")
        if rules.apply([{"jan": jan}])[0].get("exclude"):
            excluded += 1
            continue
        # End at the warehouse's latest observed date, not the product's last sale.
        dates = frame.loc[frame["unique_id"].str.startswith(center + ":"), "ds"]
        end = dates.max()
        start = end - pd.Timedelta(days=27)
        window = group[group["ds"].between(start, end)]
        recognized = set(window["ds"])
        missing = [d.date().isoformat() for d in pd.date_range(start, end) if d not in recognized]
        item = {
            "source_center": center,
            "jan": jan,
            "required_start": start.date().isoformat(),
            "required_end": end.date().isoformat(),
            "recognized_days": len(recognized),
            "required_days": 28,
            "missing_dates": missing,
            "eligible": not missing,
        }
        series.append(item)
        if mode == "C":
            window = window.set_index("ds").reindex(pd.date_range(start,end))
            window.index.name = "ds"
            window["unique_id"] = uid
            window = window.reset_index()
            capability = missing_capability(window,end)
            matching = next((s for s in check["series"] if s["jan"] == jan
                             and s["warehouse"] == center), None)
            item["eligible"] = bool(capability["supported"] and matching
                                     and matching["provisional_eligible"])
            item["reason"] = capability["reason"]
        if item["eligible"]:
            predictions.extend(
                forecast(
                    window, paths.state, f"demand-{analysis_id[:16]}-{jan}-{center}", horizon=14
                )
            )
    result = {
        "format": "portable-reference-demand-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "analysis_id": analysis_id,
        "prepared_sha256": report["prepared_sha256"],
        "formal_approval": False,
        "provisional": mode == "C",
        "forecast_mode": mode,
        "quality_check_id": check["id"],
        "actor": actor,
        "unit": unit,
        "series": series,
        "predictions": predictions,
        "excluded_series": excluded,
        "inventory": None,
        "inventory_risk_evaluated": False,
        "notice": (
            "暫定予測：欠損を残した出荷数量の参考値。在庫は未評価です。" if mode == "C" else
            "出荷数量の参考予測のみ。在庫・補充・正式出荷指示ではありません。"
        ),
    }
    key = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    result["request_id"] = key
    target = paths.results / f"demand-{key}.json"
    if not target.exists():
        atomic_json(target, result)
    from .forecast_verification import ForecastVerification

    ForecastVerification(paths.state / "forecast-verification.sqlite3").capture(
        "demand:" + key,
        predictions,
        {
            "created_at": result["created_at"],
            "unit": unit,
            "scope": None,
            "model": "builtin-baseline:seasonal_naive_7",
            "train_start": str(frame["ds"].min())[:10],
            "train_end": str(frame["ds"].max())[:10],
            "provisional": mode == "C",
            "forecast_mode": mode,
            "quality_check_id": check["id"],
        },
    )
    quality.store.save("execution",analysis_id,{
        "source":"demand:"+key,"quality_check_id":check["id"],"mode":mode,
        "provisional":mode=="C","actor":actor,"reason":str(value.get("reason") or "単位確認"),
        "created_at":result["created_at"],"imputation":None,
        "missing_record_count":check["missing_record_count"],
        "status":"COMPLETED" if predictions else "BLOCKED"})
    return result
