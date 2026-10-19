"""Read model only: forecast sums and existing risk judgments, no new engine."""

import csv
import hashlib
import io
import json
from collections import defaultdict
from decimal import Decimal

from .field_source import source_metadata
from .forecast_verification import ForecastVerification

REASONS = {
    "HISTORY_LESS_THAN_28_DAYS": "出荷履歴が28日未満",
    "RECENT_SOURCE_DAYS_MISSING": "直近の出荷ファイルが不足",
    "INVENTORY_SHIPMENT_AS_OF_MISMATCH": "在庫と出荷の基準日が不一致",
    "STOCKOUT_RISK": "在庫不足の可能性",
    "EXPIRY_RISK": "賞味期限に注意",
}


def build_view(daily, analysis_id, resolve):
    state = daily.view(analysis_id)
    if not state.get("build_id"):
        raise ValueError("データ確認・予測の後に結果を表示できます")
    source = daily.forecast.view(state["registration_id"])
    manifest = source["latest"]
    names, input_issues = source_metadata(daily.paths, analysis_id)
    handoff = daily.pipeline.get_handoff(state["handoff_id"])
    snapshot_times = {f["source_center"]: f["snapshot_at"] for f in handoff["files"]}
    predictions = (
        [] if not manifest["eligible_series_count"] else resolve("production", state["build_id"])
    )
    groups = defaultdict(list)
    for prediction in predictions:
        groups[prediction["unique_id"]].append(prediction)
    identities = {(v["source_center"], v["jan"]): v for v in source["identity_proposal"]}
    summary = (
        daily.production.projection.get_summary(state["summary_key"])
        if state.get("summary_key")
        else {}
    )
    risks = {(r["warehouse_id"], r["jan"]): r for r in summary.get("rows", [])}
    inventory = {r["unique_id"]: r.get("current_inventory_cases") for r in manifest["predictions"]}
    rows = []
    for series in manifest["series"]:
        uid = series["unique_id"]
        identity = identities[(series["source_center"], series["jan"])]
        risk = risks.get((identity["warehouse_id"], series["jan"]))
        values = groups.get(uid, [])
        labels = sorted(names.get((series["source_center"], series["jan"]), []))
        reasons = [REASONS.get(r, "入力条件の確認が必要") for r in series["blocking_reasons"]]
        if len(labels) > 1:
            reasons.append("原本の商品名が複数あります")
        if risk:
            reasons.extend(REASONS.get(r, r) for r in risk["risk_flags"])
        else:
            reasons.append("在庫・賞味期限リスクは未評価")
        if not values:
            reasons.append("予測できません")
        category = (
            "ACTION"
            if risk and "STOCKOUT_RISK" in risk["risk_flags"]
            else ("CHECK" if reasons else "OK")
        )
        dates = sorted(str(p["target_date"])[:10] for p in values)
        rows.append(
            {
                "item": uid,
                "jan": series["jan"],
                "name": "／".join(labels) if labels else "商品名未登録",
                "name_source": "原本在庫CSV" if labels else None,
                "warehouse": series["source_center"],
                "warehouse_id": identity["warehouse_id"],
                "period": [dates[0], dates[-1]] if dates else [],
                "unit": "箱",
                "inventory_date": snapshot_times.get(
                    series["source_center"], series["inventory_snapshot_date"]
                ),
                "inventory": inventory.get(uid),
                "forecast": float(sum((Decimal(str(p["yhat"])) for p in values), Decimal(0)))
                if values
                else None,
                "category": category,
                "reasons": reasons,
            }
        )
    value = {
        "analysis_id": analysis_id,
        "build_id": state["build_id"],
        "summary_key": state.get("summary_key"),
        "rows": rows,
        "unresolved": state.get("blockers", []),
        "input_issues": input_issues,
        "notice": "出荷実績に基づく需要の参考予測です。正式な出荷指示ではありません。",
    }
    value["result_id"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return value


def with_reviews(value, store):
    history = store.history(value["result_id"])
    latest = {r["item"]: r for r in history}
    ledger = ForecastVerification(store.path.parent / "forecast-verification.sqlite3")
    rows = [
        r
        | {
            "review": latest.get(r["item"]),
            "edit_state": ledger.edit_state(
                r["period"][0] if r.get("period") else "1900-01-01",
                ledger.actual(
                    r["item"],
                    r["period"][0] if r.get("period") else "1900-01-01",
                    "CASE",
                    "formal-jan-warehouse",
                )["status"],
            ),
        }
        for r in value["rows"]
    ]
    required = [r for r in rows if r["category"] != "OK"]
    pending = sum(r["review"] is None for r in required)
    held = sum(r["review"] is not None and r["review"]["choice"] == "HOLD" for r in required)
    return value | {
        "rows": rows,
        "counts": {
            "total": len(rows),
            "action": sum(r["category"] == "ACTION" for r in rows),
            "check": sum(r["category"] == "CHECK" for r in rows),
            "ok": sum(r["category"] == "OK" for r in rows),
            "forecastable": sum(r["forecast"] is not None for r in rows),
            "pending": pending,
            "held": held,
            "saved": len(required) - pending - held,
            "complete": pending == 0,
        },
    }


def page(value, query="", warehouse="", attention=False, offset=0, limit=30):
    rows = value["rows"]
    matches = [
        r
        for r in rows
        if query.casefold() in f"{r['jan']} {r['name']} {r['item']}".casefold()
        and (not warehouse or r["warehouse"] == warehouse)
        and (not attention or r["category"] != "OK")
    ]
    return value | {
        "rows": matches[offset : offset + limit],
        "matched": len(matches),
        "warehouses": sorted({r["warehouse"] for r in rows}),
    }


def export(value, selected):
    rows = value["rows"]
    if selected is not None:
        if (
            not isinstance(selected, list)
            or not selected
            or not all(isinstance(x, str) for x in selected)
        ):
            raise ValueError("商品を選択してください")
        if set(selected) - {r["item"] for r in rows}:
            raise ValueError("選択した商品がこの結果にありません")
        rows = [r for r in rows if r["item"] in selected]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "JAN",
            "倉庫",
            "在庫基準日",
            "予測開始",
            "予測終了",
            "単位",
            "元の期間予測",
            "担当者修正数量",
            "判断",
            "理由",
            "コメント",
            "担当者",
            "保存日時",
            "注意理由",
        ]
    )
    for row in rows:
        review = row.get("review") or {}
        values = [
            row["jan"],
            row["warehouse"],
            row["inventory_date"],
            *(row["period"] or ["", ""]),
            row["unit"],
            row["forecast"],
            review.get("quantity"),
            *[review.get(k, "") for k in ("choice", "reason", "comment", "actor", "created_at")],
            "／".join(row["reasons"]),
        ]
        writer.writerow([safe_csv(v) for v in values])
    return output.getvalue().encode("utf-8-sig")


def safe_csv(value):
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
