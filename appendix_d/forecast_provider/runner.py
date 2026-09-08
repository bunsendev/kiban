"""日次集計済み入力を使う固定学習run。原本取込・名寄せは上流の責務。"""

from __future__ import annotations

import traceback

import pandas as pd

from .contracts import PREDICT_REQUIRED_COLUMNS, ForecastDataset, ProviderConfig, RunContext
from .errors import ContractViolationError, ProviderError
from .evaluation import build_plan, reconcile_predictions
from .features import attach_features
from .frames import quantiles_from_interval_levels, validate_train_frame
from .registry import registry


def available_history(
    data: pd.DataFrame,
    origin: pd.Timestamp,
    *,
    availability_mode: str,
    known_future_columns: tuple[str, ...] = (),
    feature_versions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """JST翌日00:00締切。利用可能時刻がない場合の仮定は呼出側が明示する。

    known_future_columns は予測時点で既知の変数であり、履歴側にも保持して
    プロバイダーへ渡す。baseline は使用しないが、runner は参照フローとして
    落としてはならない。
    """
    if availability_mode not in ("ASSUMED", "OBSERVED"):
        raise ContractViolationError("availability_modeを明示します")
    mask = data.ds.le(origin)
    out = data.loc[mask, ["unique_id", "ds", "y"]].copy()
    if availability_mode == "OBSERVED":
        if "available_at" not in data:
            raise ContractViolationError("OBSERVEDにはavailable_atが必要です")
        times = data.loc[mask, "available_at"]
        if (
            not pd.api.types.is_datetime64_any_dtype(times)
            or getattr(times.dtype, "tz", None) is None
            or times.isna().any()
        ):
            raise ContractViolationError("available_atはtimezone付き・非欠損日時です")
        cutoff = (origin + pd.Timedelta(days=1)).tz_localize("Asia/Tokyo")
        # 締切後に到着した実績は日付行を削除せず、当時未観測だった値としてNaN保持する。
        late = times.gt(cutoff).to_numpy()
        out.loc[late, "y"] = float("nan")
    validate_train_frame(out)
    if known_future_columns:
        targets = out[["unique_id", "ds"]].rename(columns={"ds": "target_date"})
        targets["origin_date"] = origin
        targets["horizon"] = (targets.target_date - origin).dt.days
        enriched = attach_features(
            targets, known_future_columns, versions=feature_versions, allow_history=True
        )
        for column in known_future_columns:
            out[column] = enriched[column].to_numpy()
    return out


def attach_known_future(
    targets: pd.DataFrame,
    data: pd.DataFrame,
    known_future_columns: tuple[str, ...],
    *,
    feature_versions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """dataは旧呼出形維持用。最終確定の列を直接将来変数として利用しない。"""
    return attach_features(targets, known_future_columns, versions=feature_versions)


def run_fixed_baseline(
    data: pd.DataFrame,
    dataset: ForecastDataset,
    config: ProviderConfig,
    context: RunContext,
    *,
    availability_mode: str,
    feature_versions: pd.DataFrame | None = None,
) -> dict:
    """1回学習→起点更新→予測→全予定照合。失敗は台帳に残す。"""
    if dataset.availability_mode != availability_mode:
        raise ContractViolationError("実験定義と実行のavailability_mode不一致")
    validate_train_frame(data)
    if not set(data.unique_id).issubset(dataset.unique_ids):
        raise ContractViolationError("入力に選定外の系列")
    provider = registry.create(config.provider_id)
    if config.provider_id != "builtin-baseline":
        raise ContractViolationError("この最小runnerはbuiltin-baselineのみ適合確認済みです")
    check = provider.validate(dataset, config)
    if not check.ok:
        raise ContractViolationError(str(check.issues))
    plan = build_plan(dataset)
    kf = tuple(dataset.known_future_columns)
    outputs, errors = [], []
    model = None

    def record(origin, exc: BaseException) -> None:
        """失敗を台帳へ残す。分類外の例外は UNCLASSIFIED_ERROR として保持する。

        仕様書9.1: 未分類の例外は NonRetryable として扱い、runは継続する。
        ContractViolationError だけは正常な欠測へ変換せず、そのまま送出する。
        """
        classified = isinstance(exc, ProviderError)
        errors.append(
            {
                "origin_date": None if origin is None else str(origin),
                "error": type(exc).__name__ if classified else "UNCLASSIFIED_ERROR",
                "exception_type": type(exc).__name__,
                "retryable": bool(getattr(exc, "retryable", False)) if classified else False,
                "message": str(exc),
                "traceback": None if classified else traceback.format_exc(),
            }
        )

    try:
        train = available_history(
            data,
            pd.Timestamp(dataset.train_end),
            availability_mode=availability_mode,
            known_future_columns=kf,
            feature_versions=feature_versions,
        )
        train = train[train.ds.ge(pd.Timestamp(dataset.train_start))]
        model = provider.fit_parameters(train, dataset, config, context)
    except ContractViolationError:
        provider.cleanup(context)
        raise
    except Exception as exc:
        record(None, exc)
        provider.cleanup(context)
        model = None

    if model is not None:
        try:
            for origin_date, targets in plan.groupby("origin_date", sort=True):
                try:
                    history = available_history(
                        data,
                        origin_date,
                        availability_mode=availability_mode,
                        known_future_columns=kf,
                        feature_versions=feature_versions,
                    )
                    history = history[history.ds.ge(pd.Timestamp(dataset.train_start))]
                    state = provider.refresh_context(model, history, origin_date.date(), context)
                    future = attach_known_future(
                        targets, data, kf, feature_versions=feature_versions
                    )
                    outputs.append(
                        provider.predict(
                            model,
                            state,
                            future,
                            sorted(targets.horizon.unique().astype(int).tolist()),
                            context,
                        )
                    )
                except ContractViolationError:
                    raise  # 不正データ・契約違反を正常な欠測へ変換しない。
                except Exception as exc:
                    record(origin_date, exc)
        finally:
            provider.cleanup(context)
    result = (
        pd.concat(outputs, ignore_index=True)
        if outputs
        else pd.DataFrame(columns=PREDICT_REQUIRED_COLUMNS)
    )
    ledger = reconcile_predictions(
        plan, result, expected_quantiles=set(quantiles_from_interval_levels(config.interval_levels))
    )
    return {
        "predictions": result,
        "ledger": ledger,
        "errors": errors,
        "availability_mode": availability_mode,
        "excluded_unique_ids": model.state["excluded_unique_ids"] if model else (),
        "fit_calls": 1,
        "unclassified_error_count": sum(e["error"] == "UNCLASSIFIED_ERROR" for e in errors),
        "status": "SUCCESS"
        if ledger.status.eq("SUCCESS").all()
        else "PARTIAL"
        if ledger.status.eq("SUCCESS").any()
        else "FAILED",
    }
