"""Build a copy-to-PC Windows x64 PyInstaller onedir package."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Windows x64でビルドしてください")
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=root / "dist" / "BunsenPortablePoC")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"既存の出力先を上書きしません: {output}")
    build = root / "build" / "portable-p1"
    package = build / "pyinstaller"
    package.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name",
        "BunsenPortable",
        "--distpath",
        str(package),
        "--workpath",
        str(build / "work"),
        "--specpath",
        str(build),
        "--paths",
        str(root),
        "--add-data",
        f"{root / 'portable' / 'api' / 'static'};portable/api/static",
        str(root / "portable" / "launcher" / "main.py"),
    ]
    subprocess.run(command, cwd=root, check=True)
    app = output / "App"
    shutil.copytree(package / "BunsenPortable", app)
    shutil.copytree(root / "portable" / "sample", output / "Sample")
    (output / "Data").mkdir()
    (output / "START_HERE.txt").write_text(
        "ブンセン予測 Windows Portable P1 技術PoC\n\n"
        "1. ZIPをPC内の書込可能な場所へ展開します。\n"
        "2. App\\BunsenPortable.exe をダブルクリックします。\n"
        "3. 自動で開く画面から Sample\\synthetic_shipments.csv を選択します。\n"
        "4. 予測を開始し、結果と履歴を確認します。\n"
        "5. 小画面の［終了］を押します。\n\n"
        "保存先: Data\\Results、ログ: Data\\Logs。これは人工データ専用PoCです。\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
