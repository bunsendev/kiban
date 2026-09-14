"""ローカルデータ検証の実動受入CLI。"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .client import AcceptanceClient, AcceptanceHttpError
from .runner import AcceptanceError, run_acceptance


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ローカル検証環境をAPIから実動受入します")
    parser.add_argument("--base-url", default="http://127.0.0.1:58000")
    parser.add_argument("--token-env", default="KIBAN_API_TOKEN")
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--mapping-id", required=True)
    parser.add_argument("--sample-rows", type=int, default=1000)
    parser.add_argument("--wait-seconds", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.environ.get(args.token_env, "")
    try:
        result = run_acceptance(
            AcceptanceClient(args.base_url, token),
            source_path=args.source_path,
            mapping_id=args.mapping_id,
            sample_rows=args.sample_rows,
            wait_seconds=args.wait_seconds,
        )
    except (AcceptanceError, AcceptanceHttpError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASSED", **result.as_dict()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
