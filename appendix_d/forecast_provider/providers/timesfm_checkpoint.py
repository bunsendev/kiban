"""TimesFM 2.5 checkpointの固定識別、取得、ローカル検証。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..errors import NonRetryableProviderError

REPOSITORY_ID = "google/timesfm-2.5-200m-pytorch"
REVISION = "1d952420fba87f3c6dee4f240de0f1a0fbc790e3"
FILENAME = "model.safetensors"
CHECKPOINT_SHA256 = "2f776efe6245e42b24bc4153ffdf61810140210e4bd3b01fb21f7aa779ab6ce8"
CHECKPOINT_SIZE = 925_181_104
CHECKPOINT_ENV = "KIBAN_TIMESFM_CHECKPOINT"
WEIGHTS_ID = (
    f"hf://{REPOSITORY_ID}@{REVISION}/{FILENAME}#sha256:{CHECKPOINT_SHA256}"
)


@dataclass(frozen=True)
class CheckpointRef:
    path: Path
    sha256: str
    size_bytes: int
    weights_id: str = WEIGHTS_ID


def resolve_checkpoint(value: str | Path | None = None) -> CheckpointRef:
    """環境変数または明示pathのローカルcheckpointを完全検証する。"""
    raw = value if value is not None else os.environ.get(CHECKPOINT_ENV)
    if raw is None or not str(raw).strip():
        raise NonRetryableProviderError(f"{CHECKPOINT_ENV}にcheckpoint pathが必要です")
    path = Path(raw).expanduser()
    if path.is_dir():
        path = path / FILENAME
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise NonRetryableProviderError("TimesFM checkpointが見つかりません") from exc
    if not resolved.is_file() or resolved.name != FILENAME:
        raise NonRetryableProviderError(f"TimesFM checkpointは{FILENAME}を指定します")
    stat = resolved.stat()
    if stat.st_size != CHECKPOINT_SIZE:
        raise NonRetryableProviderError("TimesFM checkpoint sizeが固定条件と一致しません")
    digest = _cached_sha256(str(resolved), stat.st_size, stat.st_mtime_ns)
    if digest != CHECKPOINT_SHA256:
        raise NonRetryableProviderError("TimesFM checkpoint SHA-256が固定条件と一致しません")
    return CheckpointRef(resolved, digest, stat.st_size)


@lru_cache(maxsize=4)
def _cached_sha256(path: str, size: int, mtime_ns: int) -> str:
    del size, mtime_ns
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_checkpoint(output: Path) -> CheckpointRef:
    """運用者が明示実行した場合だけ固定revisionを取得する。"""
    from huggingface_hub import hf_hub_download

    output.mkdir(parents=True, exist_ok=True)
    downloaded = hf_hub_download(
        repo_id=REPOSITORY_ID,
        filename=FILENAME,
        revision=REVISION,
        local_dir=output,
    )
    _cached_sha256.cache_clear()
    return resolve_checkpoint(downloaded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("fetch", "verify"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    ref = (
        fetch_checkpoint(args.output)
        if args.command == "fetch"
        else resolve_checkpoint(args.output)
    )
    print(
        json.dumps(
            {
                "path": str(ref.path),
                "sha256": ref.sha256,
                "size_bytes": ref.size_bytes,
                "weights_id": ref.weights_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
