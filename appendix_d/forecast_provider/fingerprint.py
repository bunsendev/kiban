"""学習条件の決定論的識別。履歴stateや実行ごとのIDは材料にしない。"""

from __future__ import annotations

import hashlib
import json
import math
import platform
from collections.abc import Mapping
from datetime import date
from numbers import Integral, Real
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .contracts import ForecastDataset, ProviderConfig, ProviderMetadata, RunContext

FINGERPRINT_VERSION = "training-conditions-v1"


def _canonical(value: Any) -> Any:
    """型を区別するJSON木。辞書・集合順序は無視し、配列順序は保持する。"""
    if value is None or isinstance(value, (str, bool)):
        return [type(value).__name__, value]
    if isinstance(value, Integral):
        return ["int", str(int(value))]
    if isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("fingerprintには有限数を指定します")
        if number != value:
            raise ValueError("fingerprintのfloat正規化で精度が失われます")
        return ["float", (0.0 if number == 0 else number).hex()]
    if type(value) is date:
        return ["date", value.isoformat()]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("fingerprintの辞書キーは文字列です")
        return ["mapping", [[key, _canonical(value[key])] for key in sorted(value)]]
    if isinstance(value, (tuple, list)):
        return ["sequence", [_canonical(item) for item in value]]
    if isinstance(value, (set, frozenset)):
        return ["set", sorted((_canonical(item) for item in value), key=_json)]
    raise ValueError(f"fingerprintで未対応の型: {type(value).__name__}")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def parameter_fingerprint(
    config: ProviderConfig,
    dataset: ForecastDataset,
    metadata: ProviderMetadata,
    context: RunContext,
    *,
    weights_id: str | None,
) -> str:
    """v2.2 §10/14: 重み・前処理・依存環境を含む学習条件識別。Noneは重み非該当。"""
    context.validate_for_origin(dataset.train_end, dataset.availability_mode)
    if config.provider_id != metadata.provider_id:
        raise ValueError("fingerprintのprovider_id不一致")
    if weights_id is not None and (not isinstance(weights_id, str) or not weights_id.strip()):
        raise ValueError("weights_idは非空文字列または非該当のNoneです")
    conditions = {
        "schema": FINGERPRINT_VERSION,
        "provider_id": metadata.provider_id,
        "provider_version": metadata.provider_version,
        "model_name": config.model,
        "params": config.params,
        "interval_levels": sorted(config.interval_levels),
        "preprocessing_version": config.preprocessing_version,
        "weights_id": weights_id,
        "dataset_snapshot_id": dataset.dataset_snapshot_id,
        "selection_version": dataset.selection_version,
        "availability_mode": dataset.availability_mode,
        "train_start": dataset.train_start,
        "train_end": dataset.train_end,
        "unique_ids": sorted(dataset.unique_ids),
        "seed": context.seed,
        # baselineのTRAIN残差キャッシュの範囲・入力列を固定する。
        "max_horizon": dataset.max_horizon,
        "known_future_columns": sorted(dataset.known_future_columns),
        "library": [metadata.library_name, metadata.library_version],
        "runtime_dependencies": sorted(metadata.runtime_dependencies),
        "container_digest": metadata.container_digest,
        "python": [platform.python_implementation(), platform.python_version()],
    }
    return hashlib.sha256(_json(_canonical(conditions)).encode("utf-8")).hexdigest()
