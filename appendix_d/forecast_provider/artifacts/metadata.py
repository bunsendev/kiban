"""Providerに依存しない参照メタデータのJSON変換。"""

from datetime import UTC, datetime

from ..contracts import ContextRef, ModelRef
from . import json_format as jf
from .contracts import ArtifactError

MODEL_FIELDS = {
    "model_id",
    "provider_id",
    "provider_version",
    "model_name",
    "fitted_at",
    "train_start_date",
    "train_end_date",
    "preprocessing_version",
    "parameter_fingerprint",
    "weights_id",
    "availability_mode",
}
CONTEXT_FIELDS = {"context_id", "model_id", "origin_date", "history_end", "cutoff_at"}


def model_to_json(model: ModelRef) -> dict:
    if not isinstance(model.fitted_at, datetime):
        raise ArtifactError("model fitted_atが不正です")
    result = {name: getattr(model, name) for name in MODEL_FIELDS}
    result["fitted_at"] = jf.instant(model.fitted_at.isoformat()).isoformat()
    for name in ("train_start_date", "train_end_date"):
        result[name] = getattr(model, name).isoformat()
    model_from_json(result)  # 保存前も同じ型検証を行う。
    return result


def model_from_json(value: dict) -> ModelRef:
    jf.keys(value, MODEL_FIELDS)
    args = dict(value)
    for name in MODEL_FIELDS - {"weights_id", "fitted_at", "train_start_date", "train_end_date"}:
        jf.text(args[name])
    args["fitted_at"] = jf.instant(args["fitted_at"])
    for name in ("train_start_date", "train_end_date"):
        args[name] = jf.day(args[name])
    try:
        return ModelRef(**args)
    except (TypeError, ValueError) as exc:
        raise ArtifactError("ModelRefメタデータ不正") from exc


def context_to_json(ref: ContextRef) -> dict:
    result = {
        "context_id": ref.context_id,
        "model_id": ref.model_id,
        "origin_date": ref.origin_date.isoformat(),
        "history_end": ref.history_end.isoformat(),
        "cutoff_at": ref.cutoff_at.astimezone(UTC).isoformat(),
    }
    context_from_json(result)
    return result


def context_from_json(value: dict) -> ContextRef:
    jf.keys(value, CONTEXT_FIELDS)
    return ContextRef(
        context_id=jf.text(value["context_id"]),
        model_id=jf.text(value["model_id"]),
        origin_date=jf.day(value["origin_date"]),
        history_end=jf.day(value["history_end"]),
        cutoff_at=jf.instant(value["cutoff_at"]),
    )
