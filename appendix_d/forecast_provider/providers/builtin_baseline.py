"""builtin-baseline — リファレンス実装（v2.9契約対応）。

前週同曜日・移動平均28日・同曜日4回平均を主baselineとし、
前年同曜日は参考baselineとして扱う。
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd

from ..contracts import (
    ContextRef,
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
from ..errors import ContractViolationError, InsufficientHistoryError
from ..fingerprint import parameter_fingerprint
from ..frames import (
    quantiles_from_interval_levels,
    validate_fit_frame,
    validate_future_frame,
    validate_history_frame,
)
from ..run_context import validate_context_ref

PROVIDER_ID = "builtin-baseline"
PROVIDER_VERSION = "2.9.0"

MODEL_METADATA: tuple[ModelMetadata, ...] = (
    ModelMetadata(
        model_id="seasonal_naive_7",
        display_name="前週同曜日",
        min_history_days=7,
        supported_horizons=(1, 400),
        supports_intervals=True,
        primary=True,
    ),
    ModelMetadata(
        model_id="moving_average_28",
        display_name="28日移動平均",
        min_history_days=28,
        supported_horizons=(1, 400),
        supports_intervals=True,
        primary=True,
    ),
    ModelMetadata(
        model_id="same_weekday_mean_4",
        display_name="同曜日直近4回平均",
        min_history_days=28,
        supported_horizons=(1, 400),
        supports_intervals=True,
        primary=True,
    ),
    ModelMetadata(
        model_id="seasonal_naive_364",
        display_name="前年同曜日",
        min_history_days=364,
        supported_horizons=(1, 400),
        supports_intervals=True,
        primary=False,
    ),
)
SUPPORTED_MODELS: dict[str, ModelMetadata] = {m.model_id: m for m in MODEL_METADATA}
DEFAULT_MODEL = "seasonal_naive_7"


class BuiltinBaselineProvider(ForecastProvider):
    """パラメータ学習を伴わないルールベースのプロバイダー。"""

    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id=PROVIDER_ID,
            provider_version=PROVIDER_VERSION,
            display_name="Baseline（前週同曜日・移動平均・同曜日平均）",
            category="基準",
            library_name="builtin",
            library_version=PROVIDER_VERSION,
            capabilities=ProviderCapabilities(
                supports_panel=True,
                supports_exogenous="none",
                supports_intervals=True,
                supports_context_refresh=True,
                requires_parameter_refit=False,
                requires_gpu=False,
                license="Apache-2.0",
                offline_capable=True,
            ),
            models=MODEL_METADATA,
            external_endpoints=(),
            runtime_dependencies=(("pandas", pd.__version__), ("numpy", np.__version__)),
        )

    def validate(self, dataset: ForecastDataset, config: ProviderConfig) -> ValidationResult:
        """実行前検証。学習・予測・ファイルI/Oは行わない。"""
        issues: list[ValidationIssue] = []

        if config.provider_id != PROVIDER_ID:
            issues.append(
                ValidationIssue(
                    code="PROVIDER_ID_MISMATCH",
                    message=(
                        f"ProviderConfig.provider_id={config.provider_id!r} は "
                        f"{PROVIDER_ID!r} と一致しません"
                    ),
                    blocking=True,
                )
            )

        model_meta = SUPPORTED_MODELS.get(config.model)
        if model_meta is None:
            issues.append(
                ValidationIssue(
                    code="BASELINE_UNKNOWN_MODEL",
                    message=(
                        f"未知のモデル指定です: {config.model}。"
                        f"利用可能: {sorted(SUPPORTED_MODELS)}"
                    ),
                    blocking=True,
                )
            )
        elif not model_meta.accepts_horizon(dataset.max_horizon):
            issues.append(
                ValidationIssue(
                    code="BASELINE_HORIZON_OUT_OF_RANGE",
                    message=f"対応範囲外のhorizonです: {dataset.max_horizon}",
                    blocking=True,
                )
            )

        if config.params:
            issues.append(
                ValidationIssue(
                    code="BASELINE_UNKNOWN_PARAMS",
                    message=f"builtin-baseline はparamsを受け付けません: {sorted(config.params)}",
                    blocking=True,
                )
            )

        if dataset.availability_mode == "OBSERVED" and config.interval_levels:
            issues.append(
                ValidationIssue(
                    code="OBSERVED_INTERVALS_UNSUPPORTED",
                    message=(
                        "v2.9のbuiltin-baselineはOBSERVED時点再現での区間残差を未実装のため、"
                        "interval_levelsは指定できません"
                    ),
                    blocking=True,
                )
            )

        try:
            quantiles_from_interval_levels(config.interval_levels)
        except ContractViolationError as exc:
            issues.append(
                ValidationIssue(
                    code="INVALID_INTERVAL_LEVEL",
                    message=str(exc),
                    blocking=True,
                )
            )

        if not dataset.full_period_evaluation_valid:
            issues.append(
                ValidationIssue(
                    code="FULL_PERIOD_EVAL_NOT_APPLICABLE",
                    message=(
                        "primary horizonによるTEST期間の被覆に欠損または重複があるため、"
                        "通期評価は算出されません。horizon別評価のみ利用可能です"
                    ),
                    blocking=False,
                )
            )

        if dataset.known_future_columns:
            issues.append(
                ValidationIssue(
                    code="BASELINE_EXOGENOUS_IGNORED",
                    message="本プロバイダーは外生変数を使用しません",
                    blocking=False,
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
        """TRAIN期間の記録と残差分布算出用系列の固定のみを行う。"""
        self._validate_config(config)
        context.validate_for_origin(dataset.train_end, dataset.availability_mode)
        if dataset.availability_mode == "OBSERVED" and config.interval_levels:
            raise ContractViolationError(
                "OBSERVEDでは各historical originのavailable_at再現が必要なため、"
                "v2.9のbuiltin-baselineは区間予測を提供しません"
            )
        frame = validate_fit_frame(train_df, dataset)
        if frame.empty:
            raise ContractViolationError("学習データが空です")

        unexpected_ids = set(frame["unique_id"]) - set(dataset.unique_ids)
        if unexpected_ids:
            raise ContractViolationError(
                f"dataset.unique_ids にない系列がtrain_dfに含まれます: {sorted(unexpected_ids)}"
            )

        model_meta = SUPPORTED_MODELS[config.model]
        train_end = dataset.train_end

        train_series: dict[str, pd.Series] = {}
        short: list[str] = []
        for uid, group in frame.groupby("unique_id", sort=True):
            s = _to_daily_series(group)
            if int(s.notna().sum()) < model_meta.min_history_days:
                short.append(uid)
                continue
            train_series[uid] = s

        if short:
            context.logger.warning(
                "min_history_days未満のため除外: %d系列 (model=%s, min=%d)",
                len(short),
                config.model,
                model_meta.min_history_days,
            )
        if not train_series:
            raise InsufficientHistoryError(
                f"全系列が最小履歴日数を満たしません (model={config.model})"
            )

        quantiles = quantiles_from_interval_levels(config.interval_levels)
        residual_cache = {
            uid: _residual_quantiles(
                series, config.model, list(range(1, dataset.max_horizon + 1)), quantiles
            )
            for uid, series in train_series.items()
        }
        missing_ids = set(dataset.unique_ids) - set(train_series) - set(short)
        short.extend(sorted(missing_ids))
        return ModelRef(
            model_id=str(uuid.uuid4()),
            provider_id=PROVIDER_ID,
            provider_version=PROVIDER_VERSION,
            model_name=config.model,
            fitted_at=datetime.now(UTC),
            train_end_date=train_end,
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
                "train_series": train_series,
                "residual_quantiles": residual_cache,
                "interval_levels": tuple(config.interval_levels),
                "excluded_unique_ids": tuple(short),
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
        """パラメータを変えず、予測に用いる履歴を起点時点へ差し替える。"""
        self._validate_model_ref(model_ref)
        self._validate_run(model_ref, context)
        context.validate_for_origin(origin_date, model_ref.availability_mode)
        if origin_date < model_ref.train_end_date:
            raise ContractViolationError(
                "origin_date は ModelRef.train_end_date 以降でなければなりません"
            )

        frame = validate_history_frame(history_df, origin_date)
        if frame.empty:
            raise ContractViolationError("履歴が空です")

        declared = set(model_ref.state["dataset_unique_ids"])
        fitted = set(model_ref.state["train_series"])
        excluded = set(model_ref.state["excluded_unique_ids"])

        # dataset に存在しない系列は実行基盤側の取り違えであり、黙って
        # 落とすと欠測件数に紛れて原因究明ができない。明示的に失敗させる。
        unexpected = sorted(set(frame["unique_id"]) - declared)
        if unexpected:
            raise ContractViolationError(
                f"dataset.unique_ids にない系列が history_df に含まれます: {unexpected}"
            )

        series: dict[str, pd.Series] = {}
        for uid, group in frame.groupby("unique_id", sort=True):
            if uid in excluded:
                # 最小履歴日数を満たさず fit_parameters で除外済み。
                # 正常な欠測として扱い、コンテキストへ含めない。
                continue
            if uid not in fitted:
                continue
            series[uid] = _to_daily_series(group).loc[: pd.Timestamp(origin_date)]

        return ContextRef(
            context_id=str(uuid.uuid4()),
            model_id=model_ref.model_id,
            origin_date=origin_date,
            history_end=frame["ds"].max().date(),
            cutoff_at=context.cutoff_at,
            state={"series": series},
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
        if "y" in future_df.columns:
            raise ContractViolationError("future_df に実績列 y が含まれています")
        if context_ref.model_id != model_ref.model_id:
            raise ContractViolationError("context_ref が別のモデルに紐づいています")
        if context_ref.history_end > context_ref.origin_date:
            raise ContractViolationError("context_ref.history_end が origin_date を超えています")

        model_meta = SUPPORTED_MODELS[model_ref.model_name]
        if not horizons or any(
            isinstance(h, bool) or not isinstance(h, int) or not model_meta.accepts_horizon(h)
            for h in horizons
        ):
            raise ContractViolationError(
                f"horizons はモデル対応範囲 {model_meta.supported_horizons} の整数で指定します"
            )
        if len(horizons) != len(set(horizons)):
            raise ContractViolationError("horizons に重複があります")

        # 実験定義の上限。モデルの対応範囲より狭いことがあり、これを超える
        # 予測を返すと forecast_values に実験定義外のhorizonが混入する。
        dataset_max_horizon = model_ref.state["dataset_max_horizon"]
        over = sorted(h for h in horizons if h > dataset_max_horizon)
        if over:
            raise ContractViolationError(
                f"dataset.max_horizon={dataset_max_horizon} を超えるhorizonです: {over}"
            )

        validate_future_frame(
            future_df,
            unique_ids=set(model_ref.state["dataset_unique_ids"]),
            max_horizon=dataset_max_horizon,
            origin_date=context_ref.origin_date,
            horizons=set(horizons),
            allowed_extra_columns=set(model_ref.state["known_future_columns"]),
        )
        required = {"unique_id", "origin_date", "target_date", "horizon"}
        missing = sorted(required - set(future_df.columns))
        if missing:
            raise ContractViolationError(f"future_df に必須列がありません: {missing}")
        if (
            future_df["unique_id"].isna().any()
            or not future_df["unique_id"]
            .map(lambda value: isinstance(value, str) and bool(value))
            .all()
        ):
            raise ContractViolationError("future_df.unique_id は空でない文字列でなければなりません")
        declared = set(model_ref.state["dataset_unique_ids"])
        unexpected = sorted(set(future_df["unique_id"]) - declared)
        if unexpected:
            raise ContractViolationError(
                f"dataset.unique_ids にない系列が future_df に含まれます: {unexpected}"
            )
        future_over = sorted({int(h) for h in future_df["horizon"] if int(h) > dataset_max_horizon})
        if future_over:
            raise ContractViolationError(
                f"dataset.max_horizon={dataset_max_horizon} を超えるhorizonが "
                f"future_df に含まれます: {future_over}"
            )

        model_name = model_ref.model_name
        series: dict[str, pd.Series] = context_ref.state["series"]
        quantiles = quantiles_from_interval_levels(model_ref.state["interval_levels"])
        origin = pd.Timestamp(context_ref.origin_date)

        target = future_df[future_df["horizon"].isin(horizons)]
        if not target.empty:
            try:
                future_origins = pd.to_datetime(target["origin_date"])
            except Exception as exc:  # pandasの変換例外を契約違反へ正規化
                raise ContractViolationError("future_df.origin_date が不正です") from exc
            if (future_origins != origin).any():
                raise ContractViolationError(
                    "future_df の origin_date が context_ref と一致しません"
                )

        rows: list[dict[str, Any]] = []
        for uid, group in target.groupby("unique_id", sort=True):
            history = series.get(uid)
            if history is None:
                continue

            resid_q = model_ref.state["residual_quantiles"][uid]

            for _, row in group.iterrows():
                target_d = pd.Timestamp(row["target_date"])
                h = int(row["horizon"])
                point = _point_forecast(history, target_d, h, model_name)
                if point is None or math.isnan(point):
                    continue
                base = {
                    "unique_id": uid,
                    "origin_date": origin,
                    "target_date": target_d,
                    "horizon": h,
                }
                rows.append(
                    {
                        **base,
                        "forecast_kind": "POINT",
                        "quantile": np.nan,
                        "yhat_raw": float(point),
                        "yhat": max(0.0, float(point)),
                    }
                )
                for q in quantiles:
                    correction = resid_q.get((h, q))
                    if correction is None:
                        continue  # 残差不足。点予測は残し区間未提供として照合する。
                    raw = float(point + correction)
                    rows.append(
                        {
                            **base,
                            "forecast_kind": "QUANTILE",
                            "quantile": q,
                            "yhat_raw": raw,
                            "yhat": max(0.0, raw),
                        }
                    )

        columns = [
            "unique_id",
            "origin_date",
            "target_date",
            "horizon",
            "forecast_kind",
            "quantile",
            "yhat_raw",
            "yhat",
        ]
        if not rows:
            return pd.DataFrame(columns=columns)

        return (
            pd.DataFrame(rows)
            .sort_values(["unique_id", "origin_date", "horizon", "quantile"], kind="stable")
            .reset_index(drop=True)
        )

    def cleanup(self, context: RunContext) -> None:
        return None

    @staticmethod
    def _validate_config(config: ProviderConfig) -> None:
        if config.provider_id != PROVIDER_ID:
            raise ContractViolationError(
                f"ProviderConfig.provider_id={config.provider_id!r} は "
                f"{PROVIDER_ID!r} と一致しません"
            )
        if config.model not in SUPPORTED_MODELS:
            raise ContractViolationError(f"未知のモデル指定です: {config.model}")
        if config.params:
            raise ContractViolationError(
                f"builtin-baseline はparamsを受け付けません: {sorted(config.params)}"
            )
        quantiles_from_interval_levels(config.interval_levels)

    @staticmethod
    def _validate_run(model_ref: ModelRef, context: RunContext) -> None:
        if (
            model_ref.state["run_id"] != context.run_id
            or model_ref.state["experiment_id"] != context.experiment_id
        ):
            raise ContractViolationError("ModelRefを別run/experimentへ暗黙共有できません")

    @staticmethod
    def _validate_model_ref(model_ref: ModelRef) -> None:
        if model_ref.provider_id != PROVIDER_ID:
            raise ContractViolationError(
                f"ModelRef.provider_id={model_ref.provider_id!r} は {PROVIDER_ID!r} と一致しません"
            )
        if model_ref.provider_version != PROVIDER_VERSION:
            raise ContractViolationError(
                f"ModelRef.provider_version={model_ref.provider_version!r} は "
                f"{PROVIDER_VERSION!r} と一致しません"
            )
        if model_ref.model_name not in SUPPORTED_MODELS:
            raise ContractViolationError(f"ModelRef.model_name が未知です: {model_ref.model_name}")


# ---------------------------------------------------------------------------
# 内部実装
# ---------------------------------------------------------------------------


def _to_daily_series(group: pd.DataFrame) -> pd.Series:
    """日次連続のSeriesへ変換する。欠落日はNaNのまま保持する。"""
    s = group.set_index("ds")["y"].astype("float64")
    full = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(full)


def _same_weekday_lags(horizon: int) -> list[int]:
    """対象日と同一曜日で、起点以前となる直近4回分のラグ日数。"""
    steps = math.ceil(horizon / 7)
    return [7 * k for k in range(steps, steps + 4)]


def _point_forecast(
    history: pd.Series,
    target_date: pd.Timestamp,
    horizon: int,
    model_name: str,
) -> float | None:
    """history（起点以前のみ）から target_date の点予測を返す。"""
    if model_name == "moving_average_28":
        origin = target_date - pd.Timedelta(days=horizon)
        window = history.reindex(pd.date_range(origin - pd.Timedelta(days=27), origin)).dropna()
        return float(window.mean()) if len(window) else None

    if model_name == "seasonal_naive_364":
        lags = [364 * math.ceil(horizon / 364)]
    else:
        lags = _same_weekday_lags(horizon)

    values = []
    for lag in lags:
        d = target_date - pd.Timedelta(days=lag)
        if d in history.index and not pd.isna(history.get(d)):
            values.append(float(history.get(d)))
    if not values:
        return None
    if model_name in ("seasonal_naive_7", "seasonal_naive_364"):
        return values[0]
    if model_name == "same_weekday_mean_4":
        return float(np.mean(values))
    raise ContractViolationError(f"未知のモデル指定です: {model_name}")


def _residual_quantiles(
    s: pd.Series,
    model_name: str,
    horizons: list[int],
    quantiles: list[float],
) -> dict[tuple[int, float], float]:
    """TRAINだけで経験残差分位を推定。点予測と中央値を混同しない。"""
    out: dict[tuple[int, float], float] = {}
    values = s.to_numpy(dtype="float64")
    for h in horizons:
        preds = _historical_forecast(values, h, model_name)
        resid = values - preds
        resid = resid[~np.isnan(resid)]
        if resid.size < 10:
            continue
        for q in quantiles:
            out[(h, q)] = float(np.quantile(resid, q))
    return out


def _historical_forecast(values: np.ndarray, horizon: int, model_name: str) -> np.ndarray:
    """対象日-horizon以前だけを使って各日のhistorical forecastを返す。"""
    n = values.size

    if model_name == "moving_average_28":
        rolled = pd.Series(values).rolling(28, min_periods=1).mean().shift(horizon)
        return rolled.to_numpy(dtype="float64")

    if model_name == "seasonal_naive_364":
        lags = [364 * math.ceil(horizon / 364)]
    else:
        lags = _same_weekday_lags(horizon)

    stacked = []
    for lag in lags:
        shifted = np.full(n, np.nan, dtype="float64")
        if lag < n:
            shifted[lag:] = values[: n - lag]
        stacked.append(shifted)
    matrix = np.vstack(stacked)

    if model_name in ("seasonal_naive_7", "seasonal_naive_364"):
        out = np.full(n, np.nan, dtype="float64")
        for candidate in matrix:
            take = np.isnan(out) & ~np.isnan(candidate)
            out[take] = candidate[take]
        return out
    if model_name == "same_weekday_mean_4":
        valid = ~np.isnan(matrix)
        counts = valid.sum(axis=0)
        sums = np.where(valid, matrix, 0.0).sum(axis=0)
        return np.divide(sums, counts, out=np.full(n, np.nan, dtype="float64"), where=counts > 0)
    raise ContractViolationError(f"未知のモデル指定です: {model_name}")


def build() -> BuiltinBaselineProvider:
    return BuiltinBaselineProvider()
