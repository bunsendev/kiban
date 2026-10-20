"""Build a copy-to-PC Windows x64 PyInstaller onedir package and ZIP."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from portable import APP_VERSION
from portable.scale_samples import write_samples

# The Portable application intentionally supports the built-in Baseline only.  A
# developer environment may also contain the comparison workers; letting
# PyInstaller discover those optional packages pulled several GB of unrelated
# ML runtimes into the field package.
EXCLUDED_MODULES = (
    "jax",
    "jaxlib",
    "keras",
    "matplotlib",
    "mlforecast",
    "numba",
    "psycopg",
    "pytest",
    "sklearn",
    "statsforecast",
    "tensorflow",
    "timesfm",
    "torch",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_operator_files(output: Path) -> None:
    (output / "Feedback接続設定_管理者.cmd").write_text(
        '@echo off\r\nstart "" "%~dp0App\\BunsenPortable.exe" --feedback-admin\r\n',
        encoding="ascii",
    )
    manual = Path(__file__).parent / "api/static/field"
    shutil.copy2(manual / "manual.html", output / "操作マニュアル.html")
    shutil.copy2(manual / "manual.css", output / "manual.css")
    guide = Path(__file__).resolve().parents[1] / "docs" / "かんたん操作マニュアル.txt"
    shutil.copy2(guide, output / "はじめに_かんたん操作マニュアル.txt")
    shutil.copy2(guide.parent / "Portable導入手順.txt", output / "最初に読む_インストール手順.txt")
    shutil.copy2(
        guide.parent / "Feedback端末設定ファイル仕様.txt",
        output / "IT担当者_端末設定ファイル仕様.txt",
    )
    (output / "ブンセン予測を起動.cmd").write_text(
        '@echo off\r\nstart "" "%~dp0App\\BunsenPortable.exe"\r\n',
        encoding="ascii",
    )
    (output / "START_HERE.txt").write_text(
        f"ブンセン予測 Windows Portable\nバージョン: {APP_VERSION}\n\n"
        "操作方法は「はじめに_かんたん操作マニュアル.txt」を開いてください。\n\n"
        "【はじめて使うとき】\n"
        "1. ZIPを右クリックし、［すべて展開］を選びます。\n"
        "2. USBやZIPの中から直接起動せず、展開したフォルダーをPC内に置きます。\n"
        "3. ［ブンセン予測を起動.cmd］をダブルクリックします。\n"
        "4. 小画面とブラウザーが開いたら、画面の手順に沿って操作します。\n"
        "5. 終了するときは小画面の［終了］を押します。\n\n"
        "【データとログ】\n"
        "投入待ち: Data\\Incoming\n"
        "処理結果: Data\\Results\n"
        "診断ログ: Data\\Logs\n"
        "更新時もDataフォルダーは削除しません。\n\n"
        "起動しない場合は、表示されたエラーコードとData\\Logsを管理担当者へ渡してください。\n",
        encoding="utf-8-sig",
    )


def write_manifest(output: Path) -> Path:
    files = sorted(
        path
        for path in output.rglob("*")
        if path.is_file() and path != output / "PACKAGE-MANIFEST.json"
    )
    manifest = {
        "format": "bunsen-portable-package-v1",
        "app_version": APP_VERSION,
        "built_at": datetime.now(UTC).isoformat(),
        "architecture": "windows-x64",
        "entrypoint": "ブンセン予測を起動.cmd",
        "files": {path.relative_to(output).as_posix(): sha256(path) for path in files},
    }
    target = output / "PACKAGE-MANIFEST.json"
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def write_archive(output: Path) -> Path:
    archive = output.parent / f"{output.name}.zip"
    if archive.exists():
        raise SystemExit(f"既存のZIPを上書きしません: {archive}")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(item for item in output.rglob("*") if item.is_file()):
            bundle.write(path, (Path(output.name) / path.relative_to(output)).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        bad = bundle.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC検査に失敗しました: {bad}")
    archive.with_suffix(".zip.sha256.txt").write_text(
        f"{sha256(archive)}  {archive.name}\n",
        encoding="ascii",
    )
    return archive


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Windows x64でビルドしてください")
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "dist" / f"BunsenPortable-{APP_VERSION}",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="ビルドPCで起動失敗を調査するためconsoleを表示する",
    )
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
        "--clean",
        "--onedir",
        "--console" if args.console else "--windowed",
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
        "--collect-data",
        "forecast_provider",
        "--add-data",
        f"{root / 'portable' / 'api' / 'static'};portable/api/static",
        "--add-data",
        f"{root / 'portable' / 'sample'};portable/sample",
        "--add-data",
        f"{root / 'portable' / 'runtime' / 'release-update-public.pem'};portable/runtime",
    ]
    for module in EXCLUDED_MODULES:
        command.extend(["--exclude-module", module])
    command.append(str(root / "portable" / "launcher" / "main.py"))
    subprocess.run(command, cwd=root, check=True)
    app = output / "App"
    shutil.copytree(package / "BunsenPortable", app)
    shutil.copytree(root / "portable" / "sample", output / "Sample")
    shutil.copy2(root / "portable" / "P1_FIELD_ACCEPTANCE.md", output / "P1_FIELD_ACCEPTANCE.md")
    write_samples(output / "ScaleSamples")
    shutil.copy2(root / "portable" / "SCALE_TEST.md", output / "SCALE_TEST.md")
    shutil.copy2(root / "docs" / "Portable_現場4ステップ操作.md", output / "現場操作手順.md")
    for guide in (
        "Portable_AIモデルと費用.md",
        "Portable_除外リスト登録.md",
        "Portable_手書き読取改善.md",
        "Portable_印刷在庫表の点検.md",
        "Portable_取込履歴と28日判定.md",
        "Portable_例外確認と単位ルール.md",
        "Portable_予測と実績の比較.md",
        "Portable_履歴期間と方式比較.md",
        "Portable_学習データのバックアップと復元.md",
    ):
        shutil.copy2(root / "docs" / guide, output / guide)
    (output / "Data").mkdir()
    write_operator_files(output)
    write_manifest(output)
    archive = write_archive(output)
    print(output)
    print(archive)
    print("SHA-256:", sha256(archive))


if __name__ == "__main__":
    main()
