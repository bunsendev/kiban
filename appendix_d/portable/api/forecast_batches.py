"""Bound Baseline fit/predict batches and reuse verified completed checkpoints."""

import hashlib
import json

from forecast_provider.providers.builtin_baseline import PROVIDER_VERSION
from portable.runtime.performance import measure, write_json

from .forecast import MODEL, forecast


def validate_batch_size(value):
    if type(value) is not int or value < 0 or value > 10000:
        raise ValueError("1回の商品数は0（一括）または1〜10000で指定してください")
    return value


def forecast_batches(frame, work_dir, run_id, *, batch_size=100, **kwargs):
    validate_batch_size(batch_size)
    ids = sorted(frame["unique_id"].unique())
    if not ids:
        return []
    size = batch_size or len(ids)
    # Original common time range is required for identical origin dates in each batch.
    if frame.groupby("unique_id")["ds"].max().nunique() != 1:
        raise ValueError("分割予測の系列基準日が一致しません")
    root = work_dir / "ForecastBatches" / hashlib.sha256(run_id.encode()).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    result = []
    with measure(
        root / "performance.json",
        stage="reference_forecast",
        details={
            "series_count": len(ids),
            "row_count": len(frame),
            "batch_size": batch_size,
            "batch_count": (len(ids) + size - 1) // size,
        },
    ) as metrics:
        reused = 0
        for start in range(0, len(ids), size):
            part = frame[frame["unique_id"].isin(ids[start : start + size])].sort_values(
                ["unique_id", "ds"], kind="stable"
            )
            identity = json.dumps(
                {
                    "model": MODEL,
                    "provider": PROVIDER_VERSION,
                    "contract": "portable-batch-v1",
                    **kwargs,
                },
                sort_keys=True,
            )
            key = hashlib.sha256(identity.encode() + part.to_csv(index=False).encode()).hexdigest()
            path = root / f"{key}.json"
            rows = None
            if path.is_file():
                try:
                    cached = json.loads(path.read_text(encoding="utf-8"))
                    body = json.dumps(cached["predictions"], sort_keys=True).encode()
                    if (
                        cached["input_sha256"] == key
                        and hashlib.sha256(body).hexdigest() == cached["output_sha256"]
                    ):
                        rows = cached["predictions"]
                        reused += 1
                except (ValueError, KeyError, OSError):
                    pass
            if rows is None:
                rows = forecast(part, work_dir, f"{run_id}-{key[:12]}", **kwargs)
                write_json(
                    path,
                    {
                        "input_sha256": key,
                        "predictions": rows,
                        "output_sha256": hashlib.sha256(
                            json.dumps(rows, sort_keys=True).encode()
                        ).hexdigest(),
                    },
                )
            result.extend(rows)
            metrics.update(completed_series=min(start + size, len(ids)), reused_batches=reused)
            write_json(root / "performance.json", metrics)
    return sorted(result, key=lambda item: (item["unique_id"], item["target_date"]))
