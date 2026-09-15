param([switch]$CheckOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force

try {
    Write-Host "[1/7] 配布ファイルを確認しています..."
    Test-KibanPackageIntegrity
    Write-Host "[2/7] Windows環境を確認しています..."
    if ([Environment]::OSVersion.Version.Major -lt 10) {
        throw "Windows 11または対応するWindows 10が必要です。"
    }
    if (-not [Environment]::Is64BitOperatingSystem) { throw "64 bit Windowsが必要です。" }

    Write-Host "[3/7] WSL 2を確認しています..."
    & wsl.exe --status *> $null
    if ($LASTEXITCODE -ne 0) {
        if ($CheckOnly) { throw "WSL 2が未設定です。" }
        if (-not (Test-Administrator)) {
            Write-Host "Windowsの確認画面で『はい』を選んでください。"
            $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
            Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments
            exit 0
        }
        & wsl.exe --install --no-distribution
        if ($LASTEXITCODE -ne 0) { throw "WSL 2をインストールできませんでした。" }
        Write-Host "PCを再起動し、再度『現場PCセットアップ』を実行してください。" -ForegroundColor Yellow
        Read-Host "Enterキーで終了"
        exit 3010
    }

    Write-Host "[4/7] Docker Desktopを確認しています..."
    Add-DockerPath
    if (-not (Test-Command "docker")) {
        if ($CheckOnly) { throw "Docker Desktopが未導入です。" }
        if (-not (Test-Command "winget")) {
            throw "Docker Desktopの自動導入に必要なwingetがありません。PC管理者へ連絡してください。"
        }
        Write-Host "Docker Desktopの利用条件を確認後、自動インストールします。"
        & winget install --exact --id Docker.DockerDesktop --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Docker Desktopをインストールできませんでした。" }
        Add-DockerPath
    }
    if ($CheckOnly) {
        Write-Host "必要な環境がそろっています。" -ForegroundColor Green
        exit 0
    }

    Write-Host "[5/7] Docker Desktopを起動しています..."
    Start-DockerDesktop
    Write-Host "[6/7] 予測基盤を構築しています。初回は数分かかります..."
    Initialize-KibanDirectories
    $connectionPath = Initialize-KibanEnvironment
    Invoke-KibanCompose @("--profile", "worker", "up", "-d", "--build", "postgres", "api", "mapping-dry-run-worker")
    Wait-KibanReady
    Install-KibanShortcuts

    Write-Host "[7/7] セットアップが完了しました。" -ForegroundColor Green
    Start-Process notepad.exe -ArgumentList "`"$connectionPath`""
    Open-KibanUi
} catch {
    Write-Host "セットアップを完了できませんでした。" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "『状態確認』または『障害情報取得』を実行し、PC管理者へ連絡してください。"
    Read-Host "Enterキーで終了"
    exit 1
}
