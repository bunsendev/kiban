"""Build the Windows Field Pilot RC self-extracting installer with IExpress.

The only payload is the already verified release ZIP and an ASCII bootstrap.
No field data, token, or local configuration is read by this builder.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
ZIP = ROOT.parent / "bunsen_field_pilot_release.zip"
VERSION = "0.1.0-field-pilot.4"
NAME = f"Bunsen-FieldPilot-{VERSION}-Setup.exe"


def _verify_powershell_syntax(path: pathlib.Path) -> None:
    command = (
        "$tokens=$null; $errors=$null; "
        "$source=Get-Content -LiteralPath $env:KIBAN_INSTALLER_SCRIPT -Raw; "
        "[System.Management.Automation.Language.Parser]::ParseInput("
        "$source,[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        env={**os.environ, "KIBAN_INSTALLER_SCRIPT": str(path)},
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode:
        raise SystemExit(f"Installer PowerShell syntax invalid: {result.stderr[-500:]}")


def _sed(source: pathlib.Path, target: pathlib.Path, *, include_key: bool) -> str:
    key_file = "FILE4=update-public.pem\n" if include_key else ""
    key_source = "%FILE4%=\n" if include_key else ""
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
FriendlyName=Bunsen Field Pilot RC4
AppLaunched=cmd.exe /c launch.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0=launch.cmd
FILE1=install.ps1
FILE2=payload.zip
FILE3=sha256.txt
{key_file}[SourceFiles]
SourceFiles0={source}
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
%FILE3%=
{key_source}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-key-file", type=pathlib.Path)
    args = parser.parse_args()
    if not ZIP.is_file() or not shutil.which("iexpress.exe"):
        raise SystemExit("release ZIP and Windows IExpress are required")
    public_key = None
    if args.public_key_file is not None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = args.public_key_file.read_bytes()
        try:
            parsed_key = serialization.load_pem_public_key(public_key)
        except ValueError as exc:
            raise SystemExit("Ed25519 update public key is required") from exc
        if len(public_key) > 8192 or not isinstance(parsed_key, Ed25519PublicKey):
            raise SystemExit("Ed25519 update public key is required")
    expected = hashlib.sha256(ZIP.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="bunsen-rc-") as temporary:
        stage = pathlib.Path(temporary)
        shutil.copyfile(ZIP, stage / "payload.zip")
        (stage / "sha256.txt").write_text(expected + "\n", encoding="ascii")
        if public_key is not None:
            (stage / "update-public.pem").write_bytes(public_key)
        (stage / "launch.cmd").write_text(
            '@echo off\r\n'
            'title Bunsen Field Pilot Setup\r\n'
            'set "LOGDIR=%LOCALAPPDATA%\\Bunsen\\FieldPilot\\InstallerLogs"\r\n'
            'if not exist "%LOGDIR%" mkdir "%LOGDIR%"\r\n'
            'echo Installer launcher started at %date% %time%>"%LOGDIR%\\launcher-last.txt"\r\n'
            '"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
            '-NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"\r\n'
            'set "SETUP_CODE=%errorlevel%"\r\n'
            'if not "%SETUP_CODE%"=="0" (\r\n'
            '  echo.\r\n'
            '  echo Setup failed with exit code %SETUP_CODE%.\r\n'
            '  echo Diagnostic folder: %LOGDIR%\r\n'
            '  echo Please take a photo of this window before closing it.\r\n'
            '  pause\r\n'
            ')\r\n'
            'exit /b %SETUP_CODE%\r\n', encoding="ascii",
        )
        (stage / "install.ps1").write_text(
            "$ErrorActionPreference = 'Stop'\n"
            "$diagnosticDir = Join-Path $env:LOCALAPPDATA 'Bunsen\\FieldPilot\\InstallerLogs'\n"
            "New-Item -ItemType Directory -Path $diagnosticDir -Force | Out-Null\n"
            "$diagnosticFile = Join-Path $diagnosticDir 'setup-last-error.txt'\n"
            "$step = 'ZIP verification'\n"
            "$setupCode = 1\n"
            "try {\n"
            "$zip = Join-Path $PSScriptRoot 'payload.zip'\n"
            "$expected = (Get-Content -LiteralPath "
            "(Join-Path $PSScriptRoot 'sha256.txt') -Raw).Trim()\n"
            "if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256)"
            ".Hash.ToLowerInvariant() -ne $expected) "
            "{ throw 'Installer payload integrity check failed.' }\n"
            "$step = 'ZIP extraction'\n"
            "$root = Join-Path $env:TEMP ('BunsenFieldPilot-' + [guid]::NewGuid().ToString('N'))\n"
            "New-Item -ItemType Directory -Path $root -Force | Out-Null\n"
            "try {\n"
            "    Expand-Archive -LiteralPath $zip -DestinationPath $root -Force\n"
            "    $setup = Join-Path $root 'appendix_d\\Field Pilotセットアップ.cmd'\n"
            "    if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) "
            "{ throw 'Setup missing.' }\n"
            "    $step = 'Update public key'\n"
            "    $key = Join-Path $PSScriptRoot 'update-public.pem'\n"
            "    if (Test-Path -LiteralPath $key) {\n"
            "        $targetKey = Join-Path $env:LOCALAPPDATA "
            "'Bunsen\\FieldPilot\\Data\\Config\\release-update-public.pem'\n"
            "        if (Test-Path -LiteralPath $targetKey) {\n"
            "            if ((Get-FileHash $key -Algorithm SHA256).Hash -ne "
            "(Get-FileHash $targetKey -Algorithm SHA256).Hash) "
            "{ throw 'Update trust root differs from installed key.' }\n"
            "        } else {\n"
            "            New-Item -ItemType Directory -Path "
            "(Split-Path $targetKey -Parent) -Force | Out-Null\n"
            "            Copy-Item -LiteralPath $key -Destination $targetKey\n"
            "        }\n"
            "    }\n"
            "    $step = 'Field Pilot setup'\n"
            "    & $setup\n"
            "    $setupCode = $LASTEXITCODE\n"
            "    if ($setupCode -ne 0) { throw \"Field Pilot setup exited: $setupCode\" }\n"
            "} finally {\n"
            "    $safeRoot = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\\') + '\\'\n"
            "    $safeTarget = [System.IO.Path]::GetFullPath($root)\n"
            "    if ($safeTarget.StartsWith($safeRoot, [StringComparison]::OrdinalIgnoreCase)) "
            "{ Remove-Item -LiteralPath $root -Recurse -Force }\n"
            "}\n"
            "Remove-Item -LiteralPath $diagnosticFile -ErrorAction SilentlyContinue\n"
            "} catch {\n"
            "    $setupCode = 1\n"
            "    $message = $_.Exception.Message\n"
            "    @(\"Time: $((Get-Date).ToString('o'))\", \"Step: $step\", "
            "\"Error: $message\") | Set-Content -LiteralPath $diagnosticFile -Encoding utf8\n"
            "    Write-Host "
            "\"インストールを完了できませんでした。処理: $step\" -ForegroundColor Red\n"
            "    Write-Host \"原因: $message\" -ForegroundColor Red\n"
            "    Write-Host \"診断ログ: $diagnosticFile\"\n"
            "}\n"
            "exit $setupCode\n", encoding="utf-8-sig",
        )
        _verify_powershell_syntax(stage / "install.ps1")
        target = stage / NAME
        directive = stage / "package.sed"
        directive.write_text(_sed(stage, target, include_key=public_key is not None),
                             encoding="ascii")
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
        if public_key is not None and (
                not (extracted / "update-public.pem").is_file()
                or (extracted / "update-public.pem").read_bytes() != public_key):
            raise SystemExit("IExpress extraction or embedded public key check failed")
        destination = ROOT / "dist" / NAME
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(target, destination)
    print(destination)
    print("SHA-256:", hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
