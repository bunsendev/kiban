"""Versioned reception, calendar and assortment rules, never guessed business facts."""

from datetime import date, time
from decimal import Decimal, InvalidOperation

DEFAULT = {"warehouses": []}


def text(value, label, maximum=100):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{label}を1〜{maximum}文字で入力してください")
    return value.strip()


def validate_rules(value):
    if not isinstance(value, dict) or set(value) != {"warehouses"}:
        raise ValueError("品質設定はwarehousesを持つJSONです")
    warehouses = value["warehouses"]
    if not isinstance(warehouses, list) or len(warehouses) > 200:
        raise ValueError("倉庫設定は200件以下です")
    result, seen = [], set()
    allowed = {
        "warehouse",
        "from",
        "to",
        "weekdays",
        "closed_dates",
        "products",
        "absence_means_zero",
        "receipt_due_time",
        "abnormal_change_cases",
        "master_jans",
    }
    for item in warehouses:
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError("倉庫設定の項目を確認してください")
        warehouse = text(item.get("warehouse"), "倉庫")
        if warehouse in seen:
            raise ValueError("同じ設定版に同じ倉庫を重複登録できません")
        seen.add(warehouse)
        start = date.fromisoformat(item.get("from", "1900-01-01")).isoformat()
        end = date.fromisoformat(item["to"]).isoformat() if item.get("to") else None
        if end and end < start:
            raise ValueError("設定期間の開始・終了を確認してください")
        weekdays = item.get("weekdays", list(range(7)))
        if not isinstance(weekdays, list) or any(
            type(d) is not int or d not in range(7) for d in weekdays
        ):
            raise ValueError("営業曜日は月曜0〜日曜6です")
        closures = item.get("closed_dates", [])
        products = item.get("products", [])
        master_jans = item.get("master_jans")
        if master_jans is not None and (
            not isinstance(master_jans, list)
            or len(master_jans) > 10000
            or any(not isinstance(j, str) or len(j) != 13 or not j.isdigit() for j in master_jans)
        ):
            raise ValueError("商品マスターのJANは13桁文字列の一覧です（10000件以下）")
        if not isinstance(closures, list) or len(closures) > 5000:
            raise ValueError("休業日の形式・件数を確認してください")
        closures = sorted({date.fromisoformat(d).isoformat() for d in closures})
        if not isinstance(products, list) or len(products) > 10000:
            raise ValueError("取扱商品は10000件以下です")
        handled, keys = [], set()
        for product in products:
            if not isinstance(product, dict) or set(product) - {"jan", "from", "to"}:
                raise ValueError("取扱期間にはjan/from/toを指定してください")
            jan = text(product.get("jan"), "JAN", 13)
            if not jan.isdigit() or len(jan) != 13 or jan in keys:
                raise ValueError("取扱商品のJANは重複しない13桁です")
            keys.add(jan)
            pstart = date.fromisoformat(product.get("from", start)).isoformat()
            pend = date.fromisoformat(product["to"]).isoformat() if product.get("to") else None
            if pend and pend < pstart:
                raise ValueError("商品の取扱期間を確認してください")
            handled.append({"jan": jan, "from": pstart, "to": pend})
        zero = item.get("absence_means_zero", False)
        if type(zero) is not bool:
            raise ValueError("出荷の商品行省略を0とする設定はtrue/falseです")
        due = item.get("receipt_due_time", "23:59")
        if not isinstance(due, str) or len(due) != 5:
            raise ValueError("受信期限はHH:MMです")
        time.fromisoformat(due)
        threshold = item.get("abnormal_change_cases")
        if threshold is not None:
            try:
                n = Decimal(str(threshold))
                if not n.is_finite() or n <= 0 or isinstance(threshold, bool):
                    raise InvalidOperation
                threshold = str(n)
            except InvalidOperation as exc:
                raise ValueError("異常変動の確認閾値は正のボール数です") from exc
        result.append(
            {
                "warehouse": warehouse,
                "from": start,
                "to": end,
                "weekdays": sorted(set(weekdays)),
                "closed_dates": closures,
                "products": sorted(handled, key=lambda p: p["jan"]),
                "absence_means_zero": zero,
                "receipt_due_time": due,
                "abnormal_change_cases": threshold,
                "master_jans": sorted(set(master_jans)) if master_jans is not None else None,
            }
        )
    return {"warehouses": sorted(result, key=lambda r: r["warehouse"])}


def warehouse_rule(rules, warehouse, day):
    value = day.isoformat() if isinstance(day, date) else day
    return next(
        (
            r
            for r in rules["warehouses"]
            if r["warehouse"] == warehouse
            and r["from"] <= value
            and (not r["to"] or value <= r["to"])
        ),
        None,
    )


def applicable(rules, warehouse, jan, day):
    rule = warehouse_rule(rules, warehouse, day)
    if rule is None:
        return True, False, None
    product = next((p for p in rule["products"] if p["jan"] == jan), None)
    handled = not product or (
        product["from"] <= day.isoformat()
        and (not product["to"] or day.isoformat() <= product["to"])
    )
    closed = day.weekday() not in rule["weekdays"] or day.isoformat() in rule["closed_dates"]
    return handled, closed, rule


def compile_rules(rules):
    """Index periods once, rather than scan the master for every product and day."""
    index = {
        r["warehouse"]: (
            r,
            {p["jan"]: p for p in r["products"]},
            set(r["weekdays"]),
            set(r["closed_dates"]),
        )
        for r in rules["warehouses"]
    }

    def lookup(warehouse, jan, day):
        entry = index.get(warehouse)
        if entry is None:
            return True, False, None
        rule, products, weekdays, closures = entry
        ds = day.isoformat()
        if ds < rule["from"] or (rule["to"] and ds > rule["to"]):
            return True, False, None
        product = products.get(jan)
        handled = not product or (
            product["from"] <= ds and (not product["to"] or ds <= product["to"])
        )
        return handled, day.weekday() not in weekdays or ds in closures, rule

    return lookup
