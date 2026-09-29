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
        launch_template = ROOT / "installer/windows/field-pilot-iexpress-launch.cmd"
        launch_text = launch_template.read_text(encoding="ascii")
        (stage / "launch.cmd").write_bytes(
            launch_text.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii")
        )
        install_template = ROOT / "installer/windows/field-pilot-iexpress-install.ps1"
        (stage / "install.ps1").write_text(
            install_template.read_text(encoding="utf-8"), encoding="utf-8-sig"
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
        for script_name in ("launch.cmd", "install.ps1"):
            embedded = extracted / script_name
            if (not embedded.is_file()
                    or embedded.read_bytes() != (stage / script_name).read_bytes()):
                raise SystemExit(f"IExpress embedded {script_name} mismatch")
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
