"""確認済み商品ごとの予測前提を、全商品を止めずに判定する。"""

from __future__ import annotations


def product_readiness(*, confirmed: bool, jan_conflict: bool = False,
                      observed_days: int = 0, source_complete: bool = True,
                      trial_policy: dict | None = None) -> dict:
    reasons = []
    if not confirmed:
        reasons.append("JAN_UNCONFIRMED")
    if jan_conflict:
        reasons.append("JAN_CONFLICT")
    if observed_days == 0:
        reasons.append("SHIPMENT_HISTORY_MISSING")
    elif observed_days < 28:
        reasons.append("SHIPMENT_HISTORY_SHORT")
    if not source_complete:
        reasons.append("SOURCE_FILES_UNREADABLE")
    if not trial_policy or trial_policy.get("unit") in ("UNKNOWN", "MIXED"):
        reasons.append("SHIPMENT_UNIT_UNCONFIRMED")
    if not trial_policy:
        reasons.append("MISSING_DAY_POLICY_UNCONFIRMED")
    # 正式予測は在庫・identity等の別Gateが必要。ここは参考試算の可否だけを返す。
    return {"trial_eligible": not reasons, "blocking_reasons": reasons}
