import hashlib
import json
import zipfile
from pathlib import Path

from portable import APP_VERSION
from portable.build_windows import (
    EXCLUDED_MODULES,
    write_archive,
    write_manifest,
    write_operator_files,
)


def test_portable_build_excludes_optional_model_runtimes() -> None:
    assert {"torch", "timesfm", "tensorflow", "statsforecast", "mlforecast"} <= set(
        EXCLUDED_MODULES
    )


def test_operator_package_has_launcher_manifest_and_verified_zip(tmp_path: Path) -> None:
    output = tmp_path / "BunsenPortable-test"
    (output / "App").mkdir(parents=True)
    (output / "App" / "BunsenPortable.exe").write_bytes(b"test-exe")
    (output / "Data").mkdir()

    write_operator_files(output)
    manifest_path = write_manifest(output)
    archive = write_archive(output)

    assert archive.name == "BunsenPortable-test.zip"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["app_version"] == APP_VERSION
    assert manifest["entrypoint"] == "ブンセン予測を起動.cmd"
    assert manifest["files"]["App/BunsenPortable.exe"] == hashlib.sha256(b"test-exe").hexdigest()
    assert archive.with_suffix(".zip.sha256.txt").is_file()
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert f"{output.name}/ブンセン予測を起動.cmd" in bundle.namelist()
