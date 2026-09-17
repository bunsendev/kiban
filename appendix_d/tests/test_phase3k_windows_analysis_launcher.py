"""Phase 3K: Windows予測OSS分析ランチャー。"""

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "installer" / "windows"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_standard_launcher_starts_data_and_three_provider_analysis_workers():
    module = _text(WINDOWS / "Kiban.Analysis.psm1")
    start = _text(WINDOWS / "analysis-start.ps1")
    standard = module.split("function Get-KibanManagedServices", 1)[0]

    for service in (
        "mapping-dry-run-worker",
        "import-worker",
        "normalization-worker",
        "daily-worker",
        "worker",
        "provider-conformance-worker",
        "comparison-campaign-worker",
        "statsforecast-worker",
        "statsforecast-conformance-worker",
        "mlforecast-worker",
        "mlforecast-conformance-worker",
    ):
        assert f'"{service}"' in standard
    assert "timesfm-worker" not in standard
    assert "Start-KibanAnalysisServices" in start
    assert "Wait-KibanAnalysisReady" in start
    assert "Open-KibanAnalysisUi" in start


def test_timesfm_is_explicit_and_guarded_by_memory_check():
    module = _text(WINDOWS / "Kiban.Analysis.psm1")
    wrapper = (ROOT / "TimesFM分析を追加起動.cmd").read_text(encoding="utf-8")

    assert "-IncludeTimesFm" in wrapper
    assert "$capacity.TotalMemoryGB -lt 15" in module
    assert "$capacity.FreeMemoryGB -lt 6" in module
    assert '"timesfm-worker", "timesfm-conformance-worker"' in module


def test_analysis_readiness_requires_services_and_provider_heartbeats():
    module = _text(WINDOWS / "Kiban.Analysis.psm1")

    assert "docker compose ps --services --status running" in module
    assert "/api/worker-status" in module
    for provider_id in ("builtin-baseline", "statsforecast-ets", "mlforecast-ridge"):
        assert f'"{provider_id}"' in module
    assert '@{ Authorization = "Bearer $token" }' in module
    assert "Write-Host $token" not in module


def test_setup_installs_analysis_shortcuts_and_connection_links():
    module = _text(WINDOWS / "Kiban.Local.psm1")

    assert 'Name = "予測OSS分析を起動"' in module
    assert 'Name = "TimesFM分析を追加起動"' in module
    assert '"http://127.0.0.1:$httpPort/ui/intake"' in module
    assert '"http://127.0.0.1:$httpPort/ui/analysis"' in module


def test_docker_start_probe_handles_a_stopped_engine_without_terminating():
    module = _text(WINDOWS / "Kiban.Local.psm1")

    assert "function Test-DockerEngine" in module
    assert '$ErrorActionPreference = "SilentlyContinue"' in module
    start = module.split("function Start-DockerDesktop", 1)[1]
    assert "Test-DockerEngine" in start
    assert "& docker info *> $null" not in start


def test_docker_socket_recovery_is_bounded_and_preserves_data_storage():
    module = _text(WINDOWS / "Kiban.Local.psm1")
    recovery = module.split("function Repair-DockerRuntimeSockets", 1)[1].split(
        "function Start-DockerDesktop", 1
    )[0]

    assert "--list --running --quiet" in recovery
    assert '$_ -ne "docker-desktop"' in recovery
    assert "Docker\\run" in recovery
    assert "docker-secrets-engine" in recovery
    assert '"$source.stale-$stamp"' in recovery
    assert "GetFullPath" in recovery and "StartsWith" in recovery
    assert "docker-desktop-data" not in recovery
    assert "factory reset" not in recovery
    assert "--shutdown" not in recovery


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShellなし")
def test_windows_analysis_scripts_parse_in_windows_powershell():
    paths = [
        WINDOWS / "Kiban.Analysis.psm1",
        WINDOWS / "analysis-start.ps1",
        WINDOWS / "status.ps1",
        WINDOWS / "stop.ps1",
        WINDOWS / "diagnostics.ps1",
    ]
    escaped = ",".join("'" + str(path).replace("'", "''") + "'" for path in paths)
    command = (
        f"$failed=$false; foreach($path in @({escaped})) {{ "
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "$path,[ref]$tokens,[ref]$errors) | Out-Null; "
        "if($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; $failed=$true } }; "
        "if($failed) { exit 1 }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_strict_mode_does_not_merge_duration_variable_with_japanese_suffix():
    local = _text(WINDOWS / "Kiban.Local.psm1")
    analysis = _text(WINDOWS / "Kiban.Analysis.psm1")

    assert "$Seconds秒" not in local
    assert "$Seconds秒" not in analysis
    assert "${Seconds}秒" in local
    assert "${Seconds}秒" in analysis


def test_windows_powershell_flattens_worker_status_json_before_filtering():
    analysis = _text(WINDOWS / "Kiban.Analysis.psm1")
    status = _text(WINDOWS / "status.ps1")

    assert "$workers | ForEach-Object { $_ } |" in analysis
    assert 'Where-Object { $_.status -in @("ONLINE", "WORKING") }' in analysis
    assert "foreach ($worker in @($workers | ForEach-Object { $_ }))" in status


def test_analysis_relaunch_skips_capacity_check_when_services_are_ready():
    launcher = _text(WINDOWS / "analysis-start.ps1")

    assert "$alreadyReady = $status.StandardReady" in launcher
    assert "if (-not $alreadyReady)" in launcher
    assert "予測OSS分析サービスは起動済みです" in launcher


def test_local_http_port_is_selected_once_and_used_by_compose_and_scripts():
    local = _text(WINDOWS / "Kiban.Local.psm1")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "function Test-KibanTcpPort" in local
    assert "function Initialize-KibanHttpPort" in local
    assert "function Get-KibanBaseUri" in local
    assert "@(58000) + @(48100..48120)" in local
    assert 'Add-Content -LiteralPath $environmentPath -Value "KIBAN_HTTP_PORT=$port"' in local
    assert "${KIBAN_HTTP_PORT:-58000}:8000" in compose


def test_docker_package_contains_every_runtime_schema_and_postgres_query_is_portable():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = project["tool"]["setuptools"]["package-data"]["forecast_provider"]
    schema_directories = {
        path.parent.relative_to(ROOT / "forecast_provider").as_posix()
        for path in (ROOT / "forecast_provider").rglob("*.sql")
    }
    missing = {
        directory
        for directory in schema_directories
        if not any(pattern.startswith(f"{directory}/") for pattern in patterns)
    }
    run_store = (ROOT / "forecast_provider" / "jobs" / "sqlite_store.py").read_text(
        encoding="utf-8"
    )

    assert not missing
    assert "cancellation_requested=0" in run_store
    assert "NOT cancellation_requested" not in run_store
    assert "int(retryable)" not in run_store


def test_forecast_worker_volume_is_initialized_for_the_non_root_runtime_user():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "chown -R 65532:65532 /var/lib/kiban" in dockerfile
    assert "worker-storage-init:" in compose
    assert "condition: service_completed_successfully" in compose
    assert compose.count("worker-storage-init:") == 5
