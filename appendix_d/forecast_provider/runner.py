"""日次集計済み入力を使う固定学習run。原本取込・名寄せは上流の責務。"""

from __future__ import annotations

import pandas as pd

from .contracts import PREDICT_REQUIRED_COLUMNS, ForecastDataset, ProviderConfig, RunContext
from .errors import ContractViolationError
from .evaluation import build_plan, reconcile_predictions
from .failures import FailureSinkError, record_failure
from .features import attach_features
from .frames import quantiles_from_interval_levels, validate_train_frame
from .registry import registry
from .run_context import validate_context_ref
from .training import (
    TrainingPolicy,
    normalize_training_policy,
    training_cutoff,
    training_dataset,
)


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


def run_provider(
    data: pd.DataFrame,
    dataset: ForecastDataset,
    config: ProviderConfig,
    context: RunContext,
    *,
    availability_mode: str,
    training_policy: TrainingPolicy = "FIXED",
    feature_versions: pd.DataFrame | None = None,
) -> dict:
    """指定方針で学習→起点更新→予測→全予定照合する。"""
    if not dataset.availability_mode == availability_mode == context.availability_mode:
        raise ContractViolationError("実験定義と実行のavailability_mode不一致")
    policy = normalize_training_policy(training_policy)
    validate_train_frame(data)
    if not set(data.unique_id).issubset(dataset.unique_ids):
        raise ContractViolationError("入力に選定外の系列")
    provider = registry.create(config.provider_id)
    check = provider.validate(dataset, config)
    if not check.ok:
        raise ContractViolationError(str(check.issues))
    plan = build_plan(dataset)
    kf = tuple(dataset.known_future_columns)
    outputs, errors = [], []
    model = None
    active_dataset = training_dataset(dataset, dataset.train_end)
    active_cutoff = dataset.train_end
    fit_calls = 1
    refit_cutoffs = []

    fit_context = context.for_origin(dataset.train_end)
    try:
        try:
            train = available_history(
                data,
                pd.Timestamp(dataset.train_end),
                availability_mode=availability_mode,
                known_future_columns=kf,
                feature_versions=feature_versions,
            )
            train = train[train.ds.ge(pd.Timestamp(dataset.train_start))]
            model = provider.fit_parameters(train, active_dataset, config, fit_context)
            refit_cutoffs.append(dataset.train_end.isoformat())
        except (ContractViolationError, FailureSinkError):
            raise
        except Exception as exc:
            record_failure(errors, fit_context, None, exc)

        for origin_date, targets in plan.groupby("origin_date", sort=True):
            origin = origin_date.date()
            desired_cutoff = training_cutoff(dataset, origin, policy)
            origin_context = context.for_origin(origin)
            if desired_cutoff != active_cutoff:
                active_cutoff = desired_cutoff
                active_dataset = training_dataset(dataset, desired_cutoff)
                fit_context = context.for_origin(desired_cutoff)
                model = None
                fit_calls += 1
                try:
                    train = available_history(
                        data,
                        pd.Timestamp(desired_cutoff),
                        availability_mode=availability_mode,
                        known_future_columns=kf,
                        feature_versions=feature_versions,
                    )
                    train = train[train.ds.ge(pd.Timestamp(dataset.train_start))]
                    model = provider.fit_parameters(
                        train, active_dataset, config, fit_context
                    )
                    refit_cutoffs.append(desired_cutoff.isoformat())
                except (ContractViolationError, FailureSinkError):
                    raise
                except Exception as exc:
                    record_failure(errors, fit_context, origin, exc)
            if model is None:
                continue
            try:
                history = available_history(
                    data,
                    origin_date,
                    availability_mode=availability_mode,
                    known_future_columns=kf,
                    feature_versions=feature_versions,
                )
                history = history[history.ds.ge(pd.Timestamp(dataset.train_start))]
                state = provider.refresh_context(
                    model, history, origin, origin_context
                )
                validate_context_ref(model, state, origin_context)
                future = attach_known_future(
                    targets, data, kf, feature_versions=feature_versions
                )
                outputs.append(
                    provider.predict(
                        model,
                        state,
                        future,
                        sorted(targets.horizon.unique().astype(int).tolist()),
                        origin_context,
                    )
                )
            except (ContractViolationError, FailureSinkError):
                raise  # 不正データ・契約違反を正常な欠測へ変換しない。
            except Exception as exc:
                record_failure(errors, origin_context, origin, exc)
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
        "training_policy": policy,
        "fit_calls": fit_calls,
        "refit_cutoffs": tuple(refit_cutoffs),
        "unclassified_error_count": sum(e["error"] == "UNCLASSIFIED_ERROR" for e in errors),
        "status": "SUCCESS"
        if ledger.status.eq("SUCCESS").all()
        else "PARTIAL"
        if ledger.status.eq("SUCCESS").any()
        else "FAILED",
    }


def run_fixed_provider(
    data: pd.DataFrame,
    dataset: ForecastDataset,
    config: ProviderConfig,
    context: RunContext,
    *,
    availability_mode: str,
    feature_versions: pd.DataFrame | None = None,
) -> dict:
    """互換用の固定学習runner。"""
    return run_provider(
        data,
        dataset,
        config,
        context,
        availability_mode=availability_mode,
        training_policy="FIXED",
        feature_versions=feature_versions,
    )


def run_monthly_provider(
    data: pd.DataFrame,
    dataset: ForecastDataset,
    config: ProviderConfig,
    context: RunContext,
    *,
    availability_mode: str,
    feature_versions: pd.DataFrame | None = None,
) -> dict:
    """月の最初の予定originで学習窓を拡大するreference runner。"""
    return run_provider(
        data,
        dataset,
        config,
        context,
        availability_mode=availability_mode,
        training_policy="MONTHLY_EXPANDING",
        feature_versions=feature_versions,
    )


def run_fixed_baseline(
    data: pd.DataFrame,
    dataset: ForecastDataset,
    config: ProviderConfig,
    context: RunContext,
    *,
    availability_mode: str,
    feature_versions: pd.DataFrame | None = None,
) -> dict:
    """旧API名を保つ固定学習runnerの互換wrapper。"""
    return run_fixed_provider(
        data,
        dataset,
        config,
        context,
        availability_mode=availability_mode,
        feature_versions=feature_versions,
    )
