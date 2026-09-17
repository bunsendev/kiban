"""MLForecast Ridgeを固定学習契約へ接続するProvider。"""

from __future__ import annotations

import importlib.metadata
import uuid
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd

from ..contracts import (
    PREDICT_REQUIRED_COLUMNS,
    ContextRef,
    ExperimentDefaults,
    ForecastDataset,
    ForecastProvider,
    ModelMetadata,
    ModelRef,
    ProviderCapabilities,
    ProviderConfig,
    ProviderMetadata,
    RunContext,
    ValidationIssue,
    ValidationResult,
)
from ..errors import ContractViolationError, InsufficientHistoryError, NonRetryableProviderError
from ..fingerprint import parameter_fingerprint
from ..frames import validate_fit_frame, validate_future_frame, validate_history_frame
from ..run_context import validate_context_ref
from .causal_series import prepare_daily_series
from .mlforecast_state import (
    MODEL_PARAMS,
    PREPROCESSING_VERSION,
    fit_ridge,
    model_signature,
    predict_ridge,
)

PROVIDER_ID = "mlforecast-ridge"
PROVIDER_VERSION = "2.9.0"
MODEL_ID = "ridge_lag_calendar"
MODEL_METADATA = ModelMetadata(
    model_id=MODEL_ID,
    display_name="MLForecast Ridge（日次lag・曜日）",
    min_history_days=56,
    supported_horizons=(1, 400),
    supports_intervals=False,
    primary=True,
)


class MLForecastRidgeProvider(ForecastProvider):
    """TRAINで学習した系列別Ridge係数を、各起点の履歴へ固定適用する。"""

    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id=PROVIDER_ID,
            provider_version=PROVIDER_VERSION,
            display_name="MLForecast Ridge",
            category="機械学習",
            library_name="mlforecast",
            library_version=importlib.metadata.version("mlforecast"),
            experiment_defaults=ExperimentDefaults(
                preprocessing_version=PREPROCESSING_VERSION,
                params=MODEL_PARAMS,
            ),
            capabilities=ProviderCapabilities(
                supports_panel=True,
                supports_exogenous="none",
                supports_intervals=False,
                supports_context_refresh=True,
                requires_parameter_refit=False,
                requires_gpu=False,
                license="Apache-2.0",
                offline_capable=True,
            ),
            models=(MODEL_METADATA,),
            external_endpoints=(),
            runtime_dependencies=tuple(
                (name, importlib.metadata.version(name))
                for name in ("mlforecast", "scikit-learn", "numpy", "pandas")
            ),
        )

    def validate(self, dataset: ForecastDataset, config: ProviderConfig) -> ValidationResult:
        issues: list[ValidationIssue] = []
        if config.provider_id != PROVIDER_ID:
            issues.append(_issue("PROVIDER_ID_MISMATCH", "provider_idが一致しません"))
        if config.model != MODEL_ID:
            issues.append(_issue("MLFORECAST_UNKNOWN_MODEL", "未知のモデル指定です"))
        elif not MODEL_METADATA.accepts_horizon(dataset.max_horizon):
            issues.append(_issue("MLFORECAST_HORIZON_OUT_OF_RANGE", "horizonが対応範囲外です"))
        if dict(config.params) != MODEL_PARAMS:
            issues.append(
                _issue(
                    "MLFORECAST_PARAMS_MISMATCH",
                    f"paramsは明示的に{MODEL_PARAMS!r}を指定します",
                )
            )
        if config.preprocessing_version != PREPROCESSING_VERSION:
            issues.append(
                _issue(
                    "MLFORECAST_PREPROCESSING_MISMATCH",
                    f"preprocessing_versionは{PREPROCESSING_VERSION!r}です",
                )
            )
        if config.interval_levels:
            issues.append(
                _issue(
                    "MLFORECAST_INTERVALS_UNSUPPORTED",
                    "固定条件の初期適合範囲はPOINT予測のみです",
                )
            )
        if dataset.known_future_columns:
            issues.append(
                ValidationIssue(
                    "MLFORECAST_EXOGENOUS_IGNORED",
                    "本Providerは外生変数を使用しません",
                    False,
                )
            )
        if not dataset.full_period_evaluation_valid:
            issues.append(
                ValidationIssue(
                    "FULL_PERIOD_EVAL_NOT_APPLICABLE",
                    "通期評価を被覆しないためhorizon別評価だけを利用します",
                    False,
                )
            )
        return ValidationResult(tuple(issues))

    def fit_parameters(
        self,
        train_df: pd.DataFrame,
        dataset: ForecastDataset,
        config: ProviderConfig,
        context: RunContext,
    ) -> ModelRef:
        self._require_valid(dataset, config)
        context.validate_for_origin(dataset.train_end, dataset.availability_mode)
        frame = validate_fit_frame(train_df, dataset)
        if frame.empty:
            raise ContractViolationError("学習データが空です")
        unexpected = sorted(set(frame.unique_id) - set(dataset.unique_ids))
        if unexpected:
            raise ContractViolationError(f"dataset外の系列がtrain_dfに含まれます: {unexpected}")

        models: dict[str, dict[str, Any]] = {}
        signatures: dict[str, str] = {}
        imputed: dict[str, int] = {}
        reasons: dict[str, str] = {}
        groups = dict(iter(frame.groupby("unique_id", sort=True)))
        for uid in dataset.unique_ids:
            group = groups.get(uid)
            if group is None:
                reasons[uid] = "NO_TRAIN_ROWS"
                continue
            series, actual_count, imputed_count = prepare_daily_series(
                group, dataset.train_start, dataset.train_end
            )
            if (
                actual_count < MODEL_METADATA.min_history_days
                or len(series) < MODEL_METADATA.min_history_days
            ):
                reasons[uid] = "INSUFFICIENT_HISTORY"
                continue
            try:
                fitted = fit_ridge(series, float(config.params["alpha"]))
                signature = model_signature(fitted)
            except Exception as exc:
                reasons[uid] = f"MODEL_FIT_FAILED:{type(exc).__name__}"
                context.logger.warning(
                    "MLForecast Ridge fit失敗: uid=%s error=%s", uid, type(exc).__name__
                )
                continue
            models[uid] = fitted
            signatures[uid] = signature
            imputed[uid] = imputed_count

        if not models:
            failed = [
                uid
                for uid, reason in reasons.items()
                if reason.startswith("MODEL_FIT_FAILED:")
            ]
            if failed:
                raise NonRetryableProviderError(
                    f"MLForecast Ridgeの学習が全対象で失敗しました: {sorted(failed)}"
                )
            raise InsufficientHistoryError("MLForecast Ridgeを学習できる系列がありません")
        excluded = tuple(uid for uid in dataset.unique_ids if uid not in models)
        return ModelRef(
            model_id=str(uuid.uuid4()),
            provider_id=PROVIDER_ID,
            provider_version=PROVIDER_VERSION,
            model_name=config.model,
            fitted_at=datetime.now(UTC),
            train_end_date=dataset.train_end,
            train_start_date=dataset.train_start,
            preprocessing_version=config.preprocessing_version,
            parameter_fingerprint=parameter_fingerprint(
                config, dataset, self.metadata(), context, weights_id=None
            ),
            weights_id=None,
            availability_mode=dataset.availability_mode,
            artifact_uri=None,
            state={
                "dataset_unique_ids": tuple(dataset.unique_ids),
                "dataset_max_horizon": dataset.max_horizon,
                "known_future_columns": tuple(dataset.known_future_columns),
                "params": dict(config.params),
                "interval_levels": tuple(config.interval_levels),
                "models": models,
                "parameter_signatures": signatures,
                "excluded_unique_ids": excluded,
                "exclusion_reasons": reasons,
                "train_imputed_counts": imputed,
                "seed": context.seed,
                "run_id": context.run_id,
                "experiment_id": context.experiment_id,
            },
        )

    def refresh_context(
        self,
        model_ref: ModelRef,
        history_df: pd.DataFrame,
        origin_date: date,
        context: RunContext,
    ) -> ContextRef:
        self._validate_model_ref(model_ref)
        self._validate_run(model_ref, context)
        context.validate_for_origin(origin_date, model_ref.availability_mode)
        if origin_date < model_ref.train_end_date:
            raise ContractViolationError("origin_dateは学習終了日以降です")
        frame = validate_history_frame(history_df, origin_date)
        if frame.empty:
            raise ContractViolationError("履歴が空です")
        unexpected = sorted(set(frame.unique_id) - set(model_ref.state["dataset_unique_ids"]))
        if unexpected:
            raise ContractViolationError(f"dataset外の系列がhistory_dfに含まれます: {unexpected}")

        groups = dict(iter(frame.groupby("unique_id", sort=True)))
        series: dict[str, pd.Series] = {}
        imputed: dict[str, int] = {}
        for uid in sorted(model_ref.state["models"]):
            group = groups.get(uid)
            if group is None:
                continue
            prepared, _, imputed_count = prepare_daily_series(
                group, model_ref.train_start_date, origin_date
            )
            if len(prepared) < MODEL_METADATA.min_history_days:
                continue
            series[uid] = prepared
            imputed[uid] = imputed_count
        return ContextRef(
            context_id=str(uuid.uuid4()),
            model_id=model_ref.model_id,
            origin_date=origin_date,
            history_end=origin_date,
            cutoff_at=context.cutoff_at,
            state={
                "series": series,
                "imputed_counts": imputed,
                "parameter_signatures": self._verified_signatures(model_ref),
            },
        )

    def predict(
        self,
        model_ref: ModelRef,
        context_ref: ContextRef,
        future_df: pd.DataFrame,
        horizons: list[int],
        context: RunContext,
    ) -> pd.DataFrame:
        self._validate_model_ref(model_ref)
        self._validate_run(model_ref, context)
        validate_context_ref(model_ref, context_ref, context)
        if context_ref.state.get("parameter_signatures") != self._verified_signatures(model_ref):
            raise ContractViolationError("context更新で学習済みパラメータが変化しました")
        if not horizons or len(horizons) != len(set(horizons)) or any(
            isinstance(h, bool)
            or not isinstance(h, int)
            or not MODEL_METADATA.accepts_horizon(h)
            or h > model_ref.state["dataset_max_horizon"]
            for h in horizons
        ):
            raise ContractViolationError("horizonsがモデルまたは実験の対応範囲外です")
        validate_future_frame(
            future_df,
            unique_ids=set(model_ref.state["dataset_unique_ids"]),
            max_horizon=model_ref.state["dataset_max_horizon"],
            origin_date=context_ref.origin_date,
            horizons=set(horizons),
            allowed_extra_columns=set(model_ref.state["known_future_columns"]),
        )

        rows: list[dict[str, Any]] = []
        maximum = max(horizons)
        selected = future_df[future_df.horizon.isin(horizons)]
        for uid, targets in selected.groupby("unique_id", sort=True):
            series = context_ref.state["series"].get(uid)
            fitted = model_ref.state["models"].get(uid)
            if series is None or fitted is None:
                continue
            before = model_signature(fitted)
            forecast = predict_ridge(fitted, series, maximum)
            if model_signature(fitted) != before:
                raise ContractViolationError("predictで学習済みパラメータが変化しました")
            for row in targets.itertuples(index=False):
                raw = float(forecast[int(row.horizon) - 1])
                rows.append(
                    {
                        "unique_id": uid,
                        "origin_date": pd.Timestamp(row.origin_date),
                        "target_date": pd.Timestamp(row.target_date),
                        "horizon": int(row.horizon),
                        "forecast_kind": "POINT",
                        "quantile": np.nan,
                        "yhat_raw": raw,
                        "yhat": max(0.0, raw),
                    }
                )
        if not rows:
            return pd.DataFrame(columns=PREDICT_REQUIRED_COLUMNS)
        return (
            pd.DataFrame(rows)
            .sort_values(["unique_id", "origin_date", "horizon"], kind="stable")
            .reset_index(drop=True)
        )

    def cleanup(self, context: RunContext) -> None:
        return None

    def _require_valid(self, dataset: ForecastDataset, config: ProviderConfig) -> None:
        blocking = [
            issue.message
            for issue in self.validate(dataset, config).issues
            if issue.blocking
        ]
        if blocking:
            raise ContractViolationError("; ".join(blocking))

    @staticmethod
    def _validate_run(model_ref: ModelRef, context: RunContext) -> None:
        if (
            model_ref.state["run_id"] != context.run_id
            or model_ref.state["experiment_id"] != context.experiment_id
        ):
            raise ContractViolationError("ModelRefを別run/experimentへ共有できません")

    @staticmethod
    def _validate_model_ref(model_ref: ModelRef) -> None:
        if (
            model_ref.provider_id != PROVIDER_ID
            or model_ref.provider_version != PROVIDER_VERSION
            or model_ref.model_name != MODEL_ID
            or model_ref.weights_id is not None
            or model_ref.preprocessing_version != PREPROCESSING_VERSION
        ):
            raise ContractViolationError("MLForecast ModelRefの識別条件が不正です")

    @staticmethod
    def _verified_signatures(model_ref: ModelRef) -> dict[str, str]:
        actual = {
            uid: model_signature(model) for uid, model in model_ref.state["models"].items()
        }
        if actual != model_ref.state["parameter_signatures"]:
            raise ContractViolationError("学習済みパラメータ署名が一致しません")
        return dict(actual)


def _issue(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, message, True)


def build() -> MLForecastRidgeProvider:
    return MLForecastRidgeProvider()
