"""Phase 2M: Windows現場PC向け自動セットアップ。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "installer" / "windows"


def _text(name: str) -> str:
    return (WINDOWS / name).read_text(encoding="utf-8-sig")


def test_field_operator_entrypoints_are_small_wrappers():
    expected = {
        "現場PCセットアップ.cmd": "setup.ps1",
        "予測基盤を起動.cmd": "start.ps1",
        "予測基盤を停止.cmd": "stop.ps1",
        "状態確認.cmd": "status.ps1",
        "障害情報取得.cmd": "diagnostics.ps1",
    }
    for filename, script in expected.items():
        value = (ROOT / filename).read_text(encoding="utf-8")
        assert "ExecutionPolicy Bypass" in value
        assert script in value


def test_setup_detects_and_installs_prerequisites_then_checks_readiness():
    setup = _text("setup.ps1")
    assert "Test-KibanPackageIntegrity" in setup
    assert "wsl.exe --install --no-distribution" in setup
    assert "Docker.DockerDesktop" in setup
    assert "--scope user" in setup
    assert "Initialize-KibanEnvironment" in setup
    assert "Wait-KibanReady" in setup
    assert "Install-KibanShortcuts" in setup


def test_setup_verifies_every_distributed_file_before_installing():
    module = _text("Kiban.Local.psm1")
    assert 'Join-Path $root "SHA256SUMS.json"' in module
    assert "Get-FileHash -LiteralPath $path -Algorithm SHA256" in module
    assert "配布ファイルが変更されています" in module


def test_generated_credentials_and_diagnostics_do_not_enter_support_record():
    module = _text("Kiban.Local.psm1")
    diagnostics = _text("diagnostics.ps1")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "RandomNumberGenerator" in module
    assert 'Join-Path $root ".env"' in module
    assert 'Join-Path $root ".kiban\\接続情報.txt"' in module
    assert ".kiban/" in gitignore
    assert "docker compose logs" not in diagnostics
    assert "Get-ChildItem Env:" not in diagnostics
    assert "接続コード、CSV本文、行値、環境変数、container logは収集していません" in diagnostics


def test_daily_scripts_preserve_database_volume():
    start = _text("start.ps1")
    stop = _text("stop.ps1")
    assert '"up", "-d", "postgres", "api", "mapping-dry-run-worker"' in start
    assert '"stop", "api", "mapping-dry-run-worker", "postgres"' in stop
    assert "down" not in stop
    assert "--volumes" not in stop
    assert 'ArgumentList "`"$connectionPath`""' in start
