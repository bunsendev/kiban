"""外部OIDC IdP接続プリフライトCLI。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import OidcPreflightSettings
from .fetcher import FetchError
from .runner import run_preflight


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="外部OIDC IdPの公開metadataとJWKSを検査します")
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--authorization-url", required=True)
    parser.add_argument("--token-url", required=True)
    parser.add_argument("--jwks-url", required=True)
    parser.add_argument("--algorithms", default="RS256")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--max-response-bytes", type=int, default=131_072)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        algorithms = tuple(value.strip() for value in args.algorithms.split(",") if value.strip())
        result = run_preflight(
            OidcPreflightSettings(
                issuer=args.issuer,
                authorization_url=args.authorization_url,
                token_url=args.token_url,
                jwks_url=args.jwks_url,
                algorithms=algorithms,
                timeout_seconds=args.timeout_seconds,
                max_response_bytes=args.max_response_bytes,
            ),
            args.output_root,
        )
    except (FetchError, OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["outcome"] == "READY_FOR_IDP_LOGIN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
