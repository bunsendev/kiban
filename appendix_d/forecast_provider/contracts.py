"""ForecastProvider共通契約 v2.9。

POINT/QUANTILE分離、日単位入力、利用可能時刻の評価条件を定義する。
月次再学習は本リファレンスの実装範囲外。完全版仕様書のE-2/E-3で追加する。
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from numbers import Integral
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable

import pandas as pd

# ---------------------------------------------------------------------------
# 固定スキーマ
# ---------------------------------------------------------------------------

TRAIN_REQUIRED_COLUMNS: tuple[str, ...] = ("unique_id", "ds", "y")

PREDICT_REQUIRED_COLUMNS: tuple[str, ...] = (
    "unique_id",
    "origin_date",
    "target_date",
    "horizon",
    "forecast_kind",
    "quantile",
    "yhat_raw",
    "yhat",
)

MEDIAN_QUANTILE: float = 0.5

#: quantile の丸め桁数。forecast_values.quantile の NUMERIC(8,6) と一致させる。
#: ここを変更する場合はDDLの精度も同じコミットで変更すること。
QUANTILE_DECIMALS: int = 6

ExogenousSupport = Literal["none", "known_future", "observed", "both"]


# ---------------------------------------------------------------------------
# 能力宣言
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderCapabilities:
    """プロバイダー全体の能力宣言。

    モデルごとに異なる最小履歴日数・horizon範囲は ModelMetadata に置く。
    """

    supports_panel: bool
    supports_exogenous: ExogenousSupport
    supports_intervals: bool
    supports_context_refresh: bool
    requires_parameter_refit: bool
    requires_gpu: bool
    license: str
    offline_capable: bool

    def __post_init__(self) -> None:
        for name in (
            "supports_panel",
            "supports_intervals",
            "supports_context_refresh",
            "requires_parameter_refit",
            "requires_gpu",
            "offline_capable",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} はboolで指定します")
        if self.supports_exogenous not in ("none", "known_future", "observed", "both"):
            raise ValueError("supports_exogenous が不正です")
        if not isinstance(self.license, str) or not self.license:
            raise ValueError("license は空でない文字列で指定します")

    @property
    def eligible_for_primary_ranking(self) -> bool:
        """主ランキング掲載の宣言上の必要条件。"""
        return self.supports_context_refresh and not self.requires_parameter_refit


@dataclass(frozen=True)
class ModelMetadata:
    """Provider内のモデル単位で異なる能力・制約。"""

    model_id: str
    display_name: str
    min_history_days: int
    supported_horizons: tuple[int, int]
    supports_intervals: bool
    primary: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id:
            raise ValueError("model_id は空でない文字列で指定します")
        if not isinstance(self.display_name, str) or not self.display_name:
            raise ValueError("display_name は空でない文字列で指定します")
        object.__setattr__(
            self, "min_history_days", _coerce_int(self.min_history_days, "min_history_days")
        )
        if self.min_history_days <= 0:
            raise ValueError("min_history_days は1以上でなければなりません")
        horizons = self.supported_horizons
        if not isinstance(horizons, (tuple, list)) or len(horizons) != 2:
            raise ValueError("supported_horizons は(min, max)の2整数で指定します")
        low = _coerce_int(self.supported_horizons[0], "supported_horizons[0]")
        high = _coerce_int(self.supported_horizons[1], "supported_horizons[1]")
        object.__setattr__(self, "supported_horizons", (low, high))
        if low <= 0 or high < low:
            raise ValueError("supported_horizons は 1 <= min <= max を満たす必要があります")
        if not isinstance(self.supports_intervals, bool) or not isinstance(self.primary, bool):
            raise ValueError("supports_intervals/primary はboolで指定します")

    def accepts_horizon(self, horizon: int) -> bool:
        low, high = self.supported_horizons
        return low <= horizon <= high


@dataclass(frozen=True)
class ProviderMetadata:
    """レジストリ登録および再現性記録に用いる識別情報。"""

    provider_id: str
    provider_version: str
    display_name: str
    capabilities: ProviderCapabilities
    models: tuple[ModelMetadata, ...]
    category: str
    library_name: str
    library_version: str
    container_digest: str | None = None
    external_endpoints: tuple[str, ...] = ()
    runtime_dependencies: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "provider_id",
            "provider_version",
            "display_name",
            "category",
            "library_name",
            "library_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} は空でない文字列で指定します")
        if not isinstance(self.models, (tuple, list)) or not self.models:
            raise ValueError("models は1件以上必要です")
        object.__setattr__(self, "models", tuple(self.models))
        if not all(isinstance(m, ModelMetadata) for m in self.models):
            raise ValueError("models はModelMetadataで指定します")
        model_ids = [m.model_id for m in self.models]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("ModelMetadata.model_id が重複しています")
        if not isinstance(self.external_endpoints, (tuple, list)):
            raise ValueError("external_endpoints は文字列の配列で指定します")
        endpoints = tuple(self.external_endpoints)
        if any(not isinstance(x, str) or not x for x in endpoints):
            raise ValueError("external_endpoints は空でない文字列で指定します")
        object.__setattr__(self, "external_endpoints", endpoints)
        if not isinstance(self.runtime_dependencies, (tuple, list)):
            raise ValueError("runtime_dependencies は(name, version)の配列で指定します")
        deps: list[tuple[str, str]] = []
        for item in self.runtime_dependencies:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("runtime_dependencies は(name, version)の配列で指定します")
            name, version = item
            if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
                raise ValueError("runtime dependencyのname/versionは空でない文字列で指定します")
            deps.append((name, version))
        object.__setattr__(self, "runtime_dependencies", tuple(deps))

    def get_model(self, model_id: str) -> ModelMetadata | None:
        return next((m for m in self.models if m.model_id == model_id), None)


# ---------------------------------------------------------------------------
# 実行時オブジェクト
# ---------------------------------------------------------------------------


def _coerce_int(value: Any, name: str) -> int:
    """整数へ正規化する。bool は数値として扱わない。

    numpy.int64 や pandas の Int64 スカラーは Integral を満たすため受理し、
    標準の int へ変換して保持する。float は暗黙の切り捨てを避けるため拒否する。
    """
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{name} はbool以外の整数で指定します: {value!r}")
    return int(value)


def _coerce_date(value: Any, name: str) -> date:
    """日付欠損・時刻・タイムゾーンを拒否し日単位に正規化する。"""
    if value is None or value is pd.NaT:
        raise ValueError(f"{name} は欠損にできません")
    if isinstance(value, datetime):
        if value.tzinfo is not None or value.time() != datetime.min.time():
            raise ValueError(f"{name} はtimezoneなしの日単位で指定します")
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError(f"{name} は date で指定します: {value!r}")


def _freeze_value(value: Any) -> Any:
    """実験設定を外部参照から変更できない値へ再帰的に固定する。"""
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("paramsのキーは空でない文字列で指定します")
            frozen[key] = _freeze_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(v) for v in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(v) for v in value)
    return value


@dataclass(frozen=True)
class ForecastDataset:
    """実験1件が対象とするデータセットと期間設計。"""

    dataset_snapshot_id: str
    selection_version: str
    unique_ids: tuple[str, ...]
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    origin_interval_days: int
    max_horizon: int
    primary_horizon_max: int
    report_horizons: tuple[int, ...] = (7, 10, 15)
    known_future_columns: tuple[str, ...] = ()
    availability_mode: str = "ASSUMED"

    def __post_init__(self) -> None:
        if self.availability_mode not in ("ASSUMED", "OBSERVED"):
            raise ValueError("availability_mode不正")
        for name in ("dataset_snapshot_id", "selection_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} は空でない文字列で指定します")
        if not isinstance(self.unique_ids, (tuple, list)):
            raise ValueError("unique_ids は文字列の配列で指定します")
        object.__setattr__(self, "unique_ids", tuple(self.unique_ids))
        if not isinstance(self.known_future_columns, (tuple, list)):
            raise ValueError("known_future_columns は文字列の配列で指定します")
        object.__setattr__(self, "known_future_columns", tuple(self.known_future_columns))
        # --- 正規化 -------------------------------------------------------
        # 実験定義はDB・CSV経由で復元されることがあり、その場合 numpy.int64 や
        # pandas.Timestamp が渡る。boolだけを弾いたうえで標準型へ正規化する。
        for name in ("origin_interval_days", "max_horizon", "primary_horizon_max"):
            object.__setattr__(self, name, _coerce_int(getattr(self, name), name))
        if not isinstance(self.report_horizons, (tuple, list)):
            raise ValueError("report_horizons は整数の配列で指定します")
        object.__setattr__(
            self,
            "report_horizons",
            tuple(
                _coerce_int(h, f"report_horizons[{i}]") for i, h in enumerate(self.report_horizons)
            ),
        )
        for name in ("train_start", "train_end", "test_start", "test_end"):
            object.__setattr__(self, name, _coerce_date(getattr(self, name), name))

        # --- 不変条件 -----------------------------------------------------
        if self.origin_interval_days <= 0:
            raise ValueError("origin_interval_days は1以上でなければなりません")
        if self.max_horizon <= 0:
            raise ValueError("max_horizon は1以上でなければなりません")
        if self.primary_horizon_max <= 0:
            raise ValueError("primary_horizon_max は1以上でなければなりません")
        if self.primary_horizon_max > self.max_horizon:
            raise ValueError("primary_horizon_max は max_horizon 以下でなければなりません")
        if self.train_start > self.train_end:
            raise ValueError("train_start は train_end 以下でなければなりません")
        if self.test_start > self.test_end:
            raise ValueError("test_start は test_end 以下でなければなりません")
        if self.train_end >= self.test_start:
            raise ValueError("TRAIN期間とTEST期間は重複できません")
        if self.test_start != self.train_end + timedelta(days=1):
            raise ValueError("test_start は train_end の翌日でなければなりません")
        if any(h <= 0 or h > self.max_horizon for h in self.report_horizons):
            raise ValueError("report_horizons はすべて1以上max_horizon以下で指定します")
        if len(self.report_horizons) != len(set(self.report_horizons)):
            raise ValueError("report_horizons に重複があります")
        if not self.unique_ids:
            raise ValueError("unique_ids は1件以上必要です")
        if len(self.unique_ids) != len(set(self.unique_ids)):
            raise ValueError("unique_ids に重複があります")
        if any(not isinstance(uid, str) or not uid for uid in self.unique_ids):
            raise ValueError("unique_ids は空でない文字列で指定します")
        if len(self.known_future_columns) != len(set(self.known_future_columns)):
            raise ValueError("known_future_columns に重複があります")
        if any(not isinstance(col, str) or not col for col in self.known_future_columns):
            raise ValueError("known_future_columns は空でない文字列で指定します")
        reserved = set(TRAIN_REQUIRED_COLUMNS) | set(PREDICT_REQUIRED_COLUMNS) | {"available_at"}
        conflict = sorted(set(self.known_future_columns) & reserved)
        if conflict:
            raise ValueError(f"known_future_columns に予約列は指定できません: {conflict}")

    def origin_dates(self) -> list[date]:
        """6.1の生成規則。train_end を起点0とし、test_end 未満まで進める。"""
        out: list[date] = []
        k = 0
        while True:
            origin = self.train_end + timedelta(days=self.origin_interval_days * k)
            if origin >= self.test_end:
                break
            out.append(origin)
            k += 1
        return out

    @property
    def full_period_evaluation_valid(self) -> bool:
        """予定上の最新起点を採用したときTEST全日を被覆できるか判定する。"""
        test_dates = {
            self.test_start + timedelta(days=i)
            for i in range((self.test_end - self.test_start).days + 1)
        }
        counts: Counter[date] = Counter()
        for origin in self.origin_dates():
            for h in range(1, self.primary_horizon_max + 1):
                target = origin + timedelta(days=h)
                if self.test_start <= target <= self.test_end:
                    counts[target] += 1

        return set(counts) == test_dates and all(counts[d] >= 1 for d in test_dates)

    @property
    def evaluation_profile(self) -> tuple[int, int]:
        """通期評価の意味を決める2値。

        被覆が成立していても、この2値が異なる通期評価は別物である。
        例えば (10, 10) は「1〜10日先の混合」、(1, 1) は「1日先のみ」で、
        いずれも全対象日を1回ずつ被覆するが、比較してはならない。
        評価結果には必ず本値を記録し、異なるプロファイルの通期評価を
        同一ランキング・同一表へ並べないこと。
        """
        return (self.origin_interval_days, self.primary_horizon_max)

    @property
    def evaluation_scope(self) -> tuple[object, ...]:
        """通期評価を同一母集団・同一期間として比較するための識別子。"""
        return (
            self.dataset_snapshot_id,
            self.selection_version,
            self.availability_mode,
            tuple(sorted(self.unique_ids)),
            self.train_start,
            self.train_end,
            self.test_start,
            self.test_end,
        )

    def full_period_comparable_with(self, other: ForecastDataset) -> bool:
        """2つの実験の通期評価を同一ランキングへ並べてよいかを判定する。

        評価プロファイルだけでなく、データスナップショット・選定・系列集合・
        TRAIN/TEST期間も同一であることを要求する。
        """
        return (
            self.full_period_evaluation_valid
            and other.full_period_evaluation_valid
            and self.evaluation_profile == other.evaluation_profile
            and self.evaluation_scope == other.evaluation_scope
        )

    def horizon_comparable_with(self, other: ForecastDataset) -> bool:
        """計画全体で比較できる必要条件。異なる起点は共通キー抽出後に比較する。"""
        return (
            self.evaluation_scope == other.evaluation_scope
            and self.origin_dates() == other.origin_dates()
            and self.max_horizon == other.max_horizon
        )


@dataclass(frozen=True)
class ProviderConfig:
    """プロバイダー固有設定。外部参照から変更できない形で保持する。"""

    provider_id: str
    model: str
    params: Mapping[str, Any] = field(default_factory=dict)
    interval_levels: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("provider_id は空でない文字列で指定します")
        if not isinstance(self.model, str) or not self.model:
            raise ValueError("model は空でない文字列で指定します")
        if not isinstance(self.params, Mapping):
            raise ValueError("params はmappingで指定します")
        object.__setattr__(self, "params", _freeze_value(dict(self.params)))
        if not isinstance(self.interval_levels, (tuple, list)):
            raise ValueError("interval_levels は配列で指定します")
        object.__setattr__(self, "interval_levels", tuple(self.interval_levels))


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    blocking: bool


@dataclass(frozen=True)
class ValidationResult:
    """事前検証の結果。blockingなissueが1件でもあれば実行しない。"""

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(i.blocking for i in self.issues)

    @classmethod
    def success(cls) -> ValidationResult:
        return cls(())


@dataclass(frozen=True)
class ModelRef:
    """パラメータ学習成果物への参照。"""

    model_id: str
    provider_id: str
    provider_version: str
    model_name: str
    fitted_at: datetime
    train_end_date: date
    artifact_uri: str | None = None
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextRef:
    """パラメータを再推定せず起点までの履歴を反映した状態への参照。"""

    context_id: str
    model_id: str
    origin_date: date
    history_end: date
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunContext:
    """実行環境。プロバイダーはここ以外のパスへ書き込んではならない。"""

    run_id: str
    experiment_id: str
    seed: int
    deadline: datetime
    input_dir: Path
    output_dir: Path
    resource_profile: str
    logger: logging.Logger


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ForecastProvider(Protocol):
    """全プロバイダーが実装する契約。"""

    def metadata(self) -> ProviderMetadata:
        """能力宣言を返す。副作用を持たず、いつ呼んでも同じ値を返すこと。"""
        ...

    def validate(self, dataset: ForecastDataset, config: ProviderConfig) -> ValidationResult:
        """実行前検証。学習・予測・ファイルI/Oを行ってはならない。"""
        ...

    def fit_parameters(
        self,
        train_df: pd.DataFrame,
        dataset: ForecastDataset,
        config: ProviderConfig,
        context: RunContext,
    ) -> ModelRef:
        """モデルパラメータの学習・推定。

        train_df は dataset.train_start〜dataset.train_end の範囲のみ許可する。
        呼出側だけでなくプロバイダー側でも範囲を検証し、TEST実績混入を防ぐ。
        主ランキングでは実験全体で1回だけ呼ぶ。
        """
        ...

    def refresh_context(
        self,
        model_ref: ModelRef,
        history_df: pd.DataFrame,
        origin_date: date,
        context: RunContext,
    ) -> ContextRef:
        """コンテキスト更新。パラメータを再推定せず履歴を反映する。"""
        ...

    def predict(
        self,
        model_ref: ModelRef,
        context_ref: ContextRef,
        future_df: pd.DataFrame,
        horizons: list[int],
        context: RunContext,
    ) -> pd.DataFrame:
        """予測。1回の呼び出しで対象horizonをまとめて返す。"""
        ...

    def cleanup(self, context: RunContext) -> None:
        """一時領域の解放。例外を送出してはならない。"""
        ...
