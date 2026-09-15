Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force

try {
    Start-DockerDesktop
    Initialize-KibanDirectories
    $connectionPath = Initialize-KibanEnvironment
    Invoke-KibanCompose @("--profile", "worker", "up", "-d", "postgres", "api", "mapping-dry-run-worker")
    Wait-KibanReady
    Start-Process notepad.exe -ArgumentList "`"$connectionPath`""
    Open-KibanUi
    Write-Host "予測基盤を起動しました。" -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host "Enterキーで終了"
    exit 1
}
