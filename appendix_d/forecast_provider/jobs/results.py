"""DB行を公開結果へ変換する。SQLite/PostgreSQLの表現差を吸収する。"""

import json
from decimal import Decimal


def origin_result(row) -> dict:
    result = dict(row)
    for name in ("model_artifact", "context_artifact"):
        if isinstance(result[name], str) and result[name].startswith("{"):
            result[name] = json.loads(result[name])
    return result


def forecast_result(row) -> dict:
    result = dict(row)
    value = result["quantile"]
    result["quantile"] = None if value in (None, "") else Decimal(str(value))
    result["yhat_raw"] = Decimal(str(result["yhat_raw"]))
    result["yhat"] = Decimal(str(result["yhat"]))
    return result


def failure_result(row) -> dict:
    result = dict(row)
    result["retryable"] = bool(result["retryable"])
    return result
