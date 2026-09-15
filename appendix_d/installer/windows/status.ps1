Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force

Write-Host "予測基盤の状態"
try {
    Add-DockerPath
    Invoke-KibanCompose @("ps")
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:58000/health" -TimeoutSec 5
    $ready = Invoke-RestMethod -Uri "http://127.0.0.1:58000/ready" -TimeoutSec 5
    Write-Host "API: $($health.status) / 準備状態: $($ready.status)"
    if ($health.status -eq "ok" -and $ready.status -eq "ready") {
        Write-Host "正常に利用できます。" -ForegroundColor Green
    } else { Write-Host "一部の準備が完了していません。" -ForegroundColor Yellow }
} catch {
    Write-Host "現在は利用できません。『予測基盤を起動』を実行してください。" -ForegroundColor Red
}
Read-Host "Enterキーで終了"
