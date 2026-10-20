"""Explicit human-confirmed quantity conversion; no missing-to-zero coercion."""

from decimal import Decimal, InvalidOperation, localcontext

from .document_ai import DocumentError


def number(value, maximum=10**12, positive=False):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > maximum or (positive and not result):
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise DocumentError("数量と換算を確認してください。空欄はゼロではありません") from None


def case_quantity(row):
    components = any(str(row.get(k) or "").strip() for k in ("case_quantity", "loose_quantity"))
    with localcontext() as context:
        context.prec = 40
        if not components:
            return number(row.get("quantity", "")) * number(
                row.get("case_factor", ""), 10**6, positive=True
            )
        if row.get("component_confirmed") is not True:
            raise DocumentError(
                "原本の数量列の対応を確認してください（ボール＝ケース、バラ＝商品1個）"
            )
        cases = number(row.get("case_quantity", ""))
        loose = number(row.get("loose_quantity", ""))
        if not loose:
            return cases
        # A finite exact CASE value is required; do not silently round a remainder.
        units = number(row.get("units_per_case", ""), 10**6, positive=True)
        total = cases + loose / units
        if total * units != cases * units + loose:
            raise DocumentError("箱への換算が割り切れません。換算方法を確認してください")
        return total
