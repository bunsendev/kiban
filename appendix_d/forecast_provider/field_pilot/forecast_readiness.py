"""確認済み商品ごとの予測前提を、全商品を止めずに判定する。"""

from __future__ import annotations


def product_readiness(*, confirmed: bool, jan_conflict: bool = False,
                      observed_days: int = 0, source_complete: bool = True) -> dict:
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
    # 履歴の日数だけでは、ゼロ出荷とファイル欠落を区別できない。
    reasons.extend(("SHIPMENT_UNIT_UNCONFIRMED", "MISSING_DAY_POLICY_UNCONFIRMED"))
    return {"forecast_eligible": not reasons, "blocking_reasons": reasons}
