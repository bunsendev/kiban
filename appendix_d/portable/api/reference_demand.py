"""Shipment-only reference forecasts; never fabricate inventory or missing days."""

import hashlib
import json

import pandas as pd

from .business_archive import atomic_json
from .document_evidence import valid_jan
from .forecast import forecast
from .product_exclusions import ProductExclusions


def demand_forecast(paths, analysis_id, value):
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
    if not report.get('prepared_sha256'):
        raise ValueError('旧版の解析です。「以前の受付済み原本を履歴へ再集計」を実行してください')
    prepared = (paths.prepared / f'{analysis_id}.csv').read_bytes()
    if hashlib.sha256(prepared).hexdigest() != report['prepared_sha256']:
        raise ValueError('出荷集計が変更されています。元の入力から再集計してください')
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
            raise ValueError('出荷CSVのJANチェック桁を確認してください')
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
        if not missing:
            predictions.extend(
                forecast(
                    window, paths.state, f"demand-{analysis_id[:16]}-{jan}-{center}", horizon=14
                )
            )
    result = {
        "format": "portable-reference-demand-v1",
        "analysis_id": analysis_id,
        "prepared_sha256": report['prepared_sha256'],
        "formal_approval": False,
        "actor": actor,
        "unit": unit,
        "series": series,
        "predictions": predictions,
        "excluded_series": excluded,
        "inventory": None,
        "inventory_risk_evaluated": False,
        "notice": "出荷数量の参考予測のみ。在庫・補充・正式出荷指示ではありません。",
    }
    key = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    result["request_id"] = key
    target = paths.results / f"demand-{key}.json"
    if not target.exists():
        atomic_json(target, result)
    return result
