"""配布ZIPと SHA256SUMS.json を生成する。

日本語ファイル名を含むため、ZIP は必ず Python の zipfile で作成する
（生成後に日本語ファイル名のUTF-8フラグを確認する）。
キャッシュ・デモ出力・仮想環境は含めない。

使い方:
    python make_release.py            # ../appendix_d.zip を生成
    python make_release.py --check    # SHA256SUMS.json を照合するだけ
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
EXCLUDE_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "demo_output"}
EXCLUDE_SUFFIX = {".egg-info"}
SUMS = "SHA256SUMS.json"


def release_files() -> list[pathlib.Path]:
    out = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        if EXCLUDE_DIRS & set(p.relative_to(ROOT).parts):
            continue
        if any(part.endswith(tuple(EXCLUDE_SUFFIX)) for part in p.parts):
            continue
        if p.suffix == ".zip" or p.name == ".env":
            continue
        if p.name == SUMS:
            continue
        out.append(p)
    return out


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sums(files: list[pathlib.Path]) -> dict[str, str]:
    sums = {p.relative_to(ROOT).as_posix(): sha256(p) for p in files}
    (ROOT / SUMS).write_text(
        json.dumps(sums, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return sums


def check_sums() -> int:
    sums = json.loads((ROOT / SUMS).read_text(encoding="utf-8"))
    actual = {p.relative_to(ROOT).as_posix() for p in release_files()}
    extras = actual - set(sums)
    for rel in sorted(extras):
        print("UNLISTED:", rel)
    bad = len(extras)
    for rel, expected in sums.items():
        p = ROOT / rel
        if not p.exists():
            print("MISSING :", rel)
            bad += 1
        elif sha256(p) != expected:
            print("MISMATCH:", rel)
            bad += 1
    print(f"{len(sums) - bad}/{len(sums)} 一致")
    return 1 if bad else 0


def build_zip(files: list[pathlib.Path]) -> pathlib.Path:
    dest = ROOT.parent / "yosoku_kiban_codex_ready_v2.9.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in [*files, ROOT / SUMS]:
            # arcname は str。zipfile は非ASCII名に自動で UTF-8 フラグを立てる。
            z.write(p, arcname=f"appendix_d/{p.relative_to(ROOT).as_posix()}")
    with zipfile.ZipFile(dest) as z:
        non_ascii = [i for i in z.infolist() if not i.filename.isascii()]
        missing_flag = [i.filename for i in non_ascii if not (i.flag_bits & 0x800)]
        if missing_flag:
            raise RuntimeError(f"UTF-8フラグが立っていません: {missing_flag}")
    return dest


def main(argv: list[str]) -> int:
    if "--check" in argv:
        return check_sums()
    files = release_files()
    sums = write_sums(files)
    dest = build_zip(files)
    print(f"{dest}  files={len(sums)}  UTF-8 flag verified")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
