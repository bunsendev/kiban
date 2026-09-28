"""Build the Windows Field Pilot RC self-extracting installer with IExpress.

The only payload is the already verified release ZIP and an ASCII bootstrap.
No field data, token, or local configuration is read by this builder.
"""

from __future__ import annotations

import hashlib
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
ZIP = ROOT.parent / "bunsen_field_pilot_release.zip"
VERSION = "0.1.0-field-pilot.1"
NAME = f"Bunsen-FieldPilot-{VERSION}-Setup.exe"


def _sed(source: pathlib.Path, target: pathlib.Path) -> str:
    return f"""[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName={target}
FriendlyName=Bunsen Field Pilot RC1
AppLaunched=cmd.exe /c launch.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0=launch.cmd
FILE1=install.ps1
FILE2=payload.zip
FILE3=sha256.txt
[SourceFiles]
SourceFiles0={source}
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
%FILE3%=
"""


def main() -> None:
    if not ZIP.is_file() or not shutil.which("iexpress.exe"):
        raise SystemExit("release ZIP and Windows IExpress are required")
    expected = hashlib.sha256(ZIP.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="bunsen-rc-") as temporary:
        stage = pathlib.Path(temporary)
        shutil.copyfile(ZIP, stage / "payload.zip")
        (stage / "sha256.txt").write_text(expected + "\n", encoding="ascii")
        (stage / "launch.cmd").write_text(
            '@echo off\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
            '-NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"\r\n'
            'exit /b %errorlevel%\r\n', encoding="ascii",
        )
        (stage / "install.ps1").write_text(
            "$ErrorActionPreference = 'Stop'\n"
            "$zip = Join-Path $PSScriptRoot 'payload.zip'\n"
            "$expected = (Get-Content -LiteralPath "
            "(Join-Path $PSScriptRoot 'sha256.txt') -Raw).Trim()\n"
            "if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256)"
            ".Hash.ToLowerInvariant() -ne $expected) "
            "{ throw 'Installer payload integrity check failed.' }\n"
            "$root = Join-Path $env:TEMP ('BunsenFieldPilot-' + [guid]::NewGuid().ToString('N'))\n"
            "New-Item -ItemType Directory -Path $root -Force | Out-Null\n"
            "try {\n"
            "    Expand-Archive -LiteralPath $zip -DestinationPath $root -Force\n"
            "    $setup = Join-Path $root 'appendix_d\\Field Pilotセットアップ.cmd'\n"
            "    if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) "
            "{ throw 'Setup missing.' }\n"
            "    & $setup\n"
            "    $setupCode = $LASTEXITCODE\n"
            "} finally {\n"
            "    $safeRoot = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\\') + '\\'\n"
            "    $safeTarget = [System.IO.Path]::GetFullPath($root)\n"
            "    if ($safeTarget.StartsWith($safeRoot, [StringComparison]::OrdinalIgnoreCase)) "
            "{ Remove-Item -LiteralPath $root -Recurse -Force }\n"
            "}\n"
            "exit $setupCode\n", encoding="utf-8-sig",
        )
        target = stage / NAME
        directive = stage / "package.sed"
        directive.write_text(_sed(stage, target), encoding="ascii")
        process = subprocess.run(
            ["iexpress.exe", "/N", "/Q", str(directive)],
            capture_output=True, text=True, timeout=180, check=False,
        )
        if process.returncode or not target.is_file() or target.stat().st_size < 100_000:
            raise SystemExit(
                f"IExpress build failed: {process.returncode} "
                f"stdout={process.stdout[-500:]} stderr={process.stderr[-500:]} "
                f"files={[p.name for p in stage.iterdir()]}"
            )
        extracted = stage / "extracted"
        check = subprocess.run(
            [str(target), "/Q", "/C", f"/T:{extracted}"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        extracted_zip = extracted / "payload.zip"
        if (check.returncode or not extracted_zip.is_file()
                or hashlib.sha256(extracted_zip.read_bytes()).hexdigest() != expected):
            raise SystemExit("IExpress extraction or embedded ZIP checksum failed")
        destination = ROOT / "dist" / NAME
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(target, destination)
    print(destination)
    print("SHA-256:", hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
