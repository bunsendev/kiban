"""ruff が使えない環境向けの最小lintゲート（標準ライブラリのみ）。

ruff が導入されている環境では `ruff check .` を正とする。
本スクリプトは ruff が無い検証コンテナでも「lintゲートを一度も通していない」
状態で出荷することを防ぐための代替であり、ruff の代わりではない。

検査項目:
  E501  行長 > MAX_LINE
  W291  行末の空白
  W191  タブインデント
  E301  ファイル末尾に改行がない
"""

from __future__ import annotations

import pathlib
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent
TARGETS = (
    "forecast_provider",
    "tests",
    "demo.py",
    "scale_check.py",
    "check_lint.py",
    "make_release.py",
)
EXCLUDE_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "demo_output"}


def max_line_length() -> int:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return int(cfg.get("tool", {}).get("ruff", {}).get("line-length", 100))


def iter_files():
    for target in TARGETS:
        path = ROOT / target
        if path.is_file():
            yield path
        elif path.is_dir():
            for p in sorted(path.rglob("*.py")):
                if not EXCLUDE_DIRS & set(p.parts):
                    yield p


def main() -> int:
    limit = max_line_length()
    problems: list[str] = []
    for path in iter_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        if text and not text.endswith("\n"):
            problems.append(f"{rel}: E301 ファイル末尾に改行がありません")
        for no, line in enumerate(text.splitlines(), 1):
            if len(line) > limit:
                problems.append(f"{rel}:{no}: E501 行長 {len(line)} > {limit}")
            if line.rstrip() != line:
                problems.append(f"{rel}:{no}: W291 行末の空白")
            if line.startswith("\t"):
                problems.append(f"{rel}:{no}: W191 タブインデント")
    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} problem(s) found.")
        return 1
    print("check_lint: All checks passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
