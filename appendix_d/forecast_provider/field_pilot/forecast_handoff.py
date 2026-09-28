"""現場の確認結果から、商品・倉庫別の正式予測への引継ぎ候補を示す。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def _approved_inventory(inventory_store, product_code: str, jan: str,
                        business_date: date) -> dict[str, str]:
    """承認済みSnapshotだけを読み、商品対応と倉庫の一致を確認する。"""

    if inventory_store is None:
        return {}
    latest: dict[str, tuple[str, str, bool]] = {}
    for snapshot in inventory_store.list_snapshots():
        snapshot_id = snapshot["snapshot_id"]
        if datetime.fromisoformat(snapshot["snapshot_at"]).astimezone(JST).date() != business_date:
            continue
        mapping_version = snapshot.get("product_mapping_version")
        if not mapping_version:
            continue
        mapped_jans = {
            record.jan for record in inventory_store.list_product_mappings(mapping_version)
            if record.source_product_code == product_code
        }
        if not mapped_jans:
            continue
        decision = inventory_store.get_latest_snapshot_decision(snapshot_id)
        job = inventory_store.get_job(snapshot["job_id"])
        reconciliation = inventory_store.get_reconciliation(snapshot["job_id"])
        valid = bool(
            decision and decision["decision"] == "APPROVED"
            and snapshot["normalized_unit"] == "CASE"
            and job and str(job.status) == "SUCCEEDED"
            and job.quarantined_row_count == 0
            and reconciliation and reconciliation["reconciled"]
        )
        for bucket in inventory_store.list_expiry_buckets_with_location(snapshot_id):
            if bucket["jan"] not in mapped_jans or bucket["location_type"] != "WAREHOUSE":
                continue
            warehouse = bucket["location_code"]
            key = (snapshot["snapshot_at"], snapshot_id)
            bucket_valid = (
                valid and bucket["jan"] == jan and bucket["normalized_unit"] == "CASE"
                and not bucket["issue_codes"]
            )
            if warehouse not in latest or key > latest[warehouse][:2]:
                latest[warehouse] = (*key, bucket_valid)
            elif key == latest[warehouse][:2]:
                latest[warehouse] = (*key, latest[warehouse][2] and bucket_valid)
    return {warehouse: snapshot_id for warehouse, (_, snapshot_id, valid) in latest.items()
            if valid}


def forecast_handoff(review: dict, trial: dict, inventory_store, *,
                     business_date: date) -> dict:
    """推測値を正式入力に昇格せず、次工程に渡せる証拠と不足理由を返す。"""

    product_code = trial["product_code"]
    confirmed = next((item for item in review["confirmed_items"]
                      if item["product_code"] == product_code), None)
    if confirmed is None:
        raise ValueError("HANDOFF_JAN_NOT_CONFIRMED")
    inventory = _approved_inventory(
        inventory_store, product_code, confirmed["jan"], business_date,
    )
    common = []
    if not review["complete"]:
        common.append("SOURCE_FILES_UNREADABLE")
    if confirmed["evidence_status"] == "JAN_CONFLICT":
        common.append("JAN_CONFLICT")
    if trial["status"] != "TRIAL_READY":
        common.extend(trial.get("reasons", []))
    if trial.get("unit") != "CASE":
        common.append("SHIPMENT_CASE_UNIT_NOT_CONFIRMED")
    series = []
    for item in trial.get("series", []):
        blockers = list(common)
        if item["used_days_in_window"] < 28:
            blockers.append("DAILY_COVERAGE_INCOMPLETE")
        if date.fromisoformat(item["last_observed_day"]) < business_date - timedelta(days=7):
            blockers.append("SHIPMENT_HISTORY_OLD")
        warehouse = item["warehouse_code"]
        snapshot_id = inventory.get(warehouse)
        if snapshot_id is None:
            blockers.append("APPROVED_CASE_INVENTORY_MISSING")
        series.append({
            "warehouse_code": warehouse,
            "last_observed_day": item["last_observed_day"],
            "observed_days_in_window": item["observed_days_in_window"],
            "inventory_snapshot_id": snapshot_id,
            "preparation_candidate": not blockers,
            "blocking_reasons": blockers,
        })
    if not series:
        common.append("SHIPMENT_SERIES_MISSING")
    return {
        "product_code": product_code, "jan": confirmed["jan"],
        "business_date": business_date.isoformat(),
        "source_fingerprint": trial.get("source_fingerprint"),
        "trial_policy_version": trial.get("policy_version"),
        "series": series, "blocking_reasons": common,
        "preparation_candidate_count": sum(item["preparation_candidate"] for item in series),
        "formal_forecast_ready": False,
        "formal_next_gate": "FORMAL_SHIPMENT_NORMALIZATION_AND_DAILY_BUILD_REQUIRED",
    }
