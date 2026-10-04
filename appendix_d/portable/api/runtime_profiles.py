"""Fixed runtime profiles allowed in the Portable SHADOW worker."""

from __future__ import annotations

from forecast_provider.providers.builtin_baseline import PROVIDER_VERSION

BASELINE_CONFIGURATION = {
    "version": "builtin-baseline-v1",
    "provider_id": "builtin-baseline",
    "model_name": "seasonal_naive_7",
    "preprocessing_version": "portable-daily-state-v1",
    "seed": 7,
    "resource_profile": "cpu-small",
    "params": {},
}

SUPPORTED_BASELINE_MODELS = frozenset({
    "seasonal_naive_7",
    "moving_average_28",
    "same_weekday_mean_4",
    "seasonal_naive_364",
})

RESOURCE_LIMITS = {
    "profile": "cpu-small",
    "max_series": 50,
    "max_history_days": 400,
    "max_horizon_days": 28,
    "max_threads": 1,
    "network_access": False,
}

ADAPTER = {
    "adapter_id": "builtin-baseline-fixed-v1",
    "provider_id": "builtin-baseline",
    "provider_version": PROVIDER_VERSION,
}


def supported_configuration(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required = {
        "version", "provider_id", "model_name", "preprocessing_version",
        "seed", "resource_profile", "params",
    }
    return (
        set(value) == required
        and isinstance(value.get("version"), str) and bool(value["version"].strip())
        and value.get("provider_id") == "builtin-baseline"
        and value.get("model_name") in SUPPORTED_BASELINE_MODELS
        and value.get("preprocessing_version") == "portable-daily-state-v1"
        and value.get("seed") == 7
        and value.get("resource_profile") == "cpu-small"
        and value.get("params") == {}
    )


def enforce_resource_limits(configuration: dict, *, series: int, history_days: int,
                            horizon_days: int) -> None:
    if not supported_configuration(configuration):
        raise ValueError("Portable Workerが対応していない実行設定です")
    values = {
        "系列数": (series, RESOURCE_LIMITS["max_series"]),
        "履歴日数": (history_days, RESOURCE_LIMITS["max_history_days"]),
        "予測日数": (horizon_days, RESOURCE_LIMITS["max_horizon_days"]),
    }
    invalid = [name for name, (actual, _) in values.items() if actual < 1]
    if invalid:
        raise ValueError("候補版の資源量は1以上です: " + "、".join(invalid))
    exceeded = [name for name, (actual, maximum) in values.items() if actual > maximum]
    if exceeded:
        raise ValueError("候補版の資源上限を超えています: " + "、".join(exceeded))
