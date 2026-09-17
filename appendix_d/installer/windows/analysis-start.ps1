param([switch]$IncludeTimesFm)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.Analysis.psm1") -Force

try {
    Write-Host "[1/5] Docker Desktopを起動しています..."
    Start-DockerDesktop
    Write-Host "[2/5] 設定とPC資源を確認しています..."
    Initialize-KibanDirectories
    $connectionPath = Initialize-KibanEnvironment
    $status = Get-KibanAnalysisStatus
    $alreadyReady = $status.StandardReady -and (-not $IncludeTimesFm -or $status.TimesFmReady)
    if (-not $alreadyReady) {
        Assert-KibanAnalysisCapacity -IncludeTimesFm:$IncludeTimesFm | Out-Null
        Write-Host "[3/5] 予測OSS分析サービスを構築・起動しています..."
        Start-KibanAnalysisServices -IncludeTimesFm:$IncludeTimesFm
    } else {
        Write-Host "[3/5] 予測OSS分析サービスは起動済みです。"
    }
    Write-Host "[4/5] APIとProvider Workerを確認しています..."
    Wait-KibanAnalysisReady -IncludeTimesFm:$IncludeTimesFm
    Write-Host "[5/5] 予測OSS分析を開始できます。" -ForegroundColor Green
    Start-Process notepad.exe -ArgumentList "`"$connectionPath`""
    Open-KibanAnalysisUi
} catch {
    Write-Host "予測OSS分析を起動できませんでした。" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "『状態確認』または『障害情報取得』を実行してください。"
    Read-Host "Enterキーで終了"
    exit 1
}
