"""クレンジング・列mappingドライランCLI。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import DryRunLimits
from .runner import run_dry_run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="台帳を更新せずCSVと列mappingをsample検査します")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--source", required=True, help="input rootからの相対path")
    parser.add_argument("--mapping-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--sample-rows", type=int, default=1_000)
    parser.add_argument("--max-source-bytes", type=int, default=100_000_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_dry_run(
            args.input_root,
            args.source,
            args.mapping_file,
            args.output_root,
            DryRunLimits(sample_rows=args.sample_rows, max_source_bytes=args.max_source_bytes),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["outcome"] == "READY_FOR_NORMALIZATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
