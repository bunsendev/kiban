Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.Analysis.psm1") -Force

Write-Host "予測基盤の状態"
try {
    Add-DockerPath
    Invoke-KibanCompose @("ps")
    $baseUri = Get-KibanBaseUri
    $health = Invoke-RestMethod -Uri "$baseUri/health" -TimeoutSec 5
    $ready = Invoke-RestMethod -Uri "$baseUri/ready" -TimeoutSec 5
    Write-Host "API: $($health.status) / 準備状態: $($ready.status)"
    $analysis = Get-KibanAnalysisStatus
    if ($analysis.StandardReady) {
        Write-Host "標準OSS分析: 起動済み" -ForegroundColor Green
    } else {
        Write-Host "標準OSS分析: 未起動または一部停止" -ForegroundColor Yellow
        Write-Host ("不足service: " + ($analysis.MissingServices -join ", "))
    }
    Write-Host ("TimesFM: " + $(if ($analysis.TimesFmReady) { "起動済み" } else { "未起動" }))
    $token = Get-KibanLocalToken
    $workers = @(Invoke-RestMethod -Uri "$baseUri/api/worker-status" `
        -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 5)
    foreach ($worker in @($workers | ForEach-Object { $_ })) {
        Write-Host ("Provider {0}: {1} / 待機 {2} / 実行中 {3}" -f `
            $worker.provider_id, $worker.status, $worker.queued_runs, $worker.running_runs)
    }
    if ($health.status -eq "ok" -and $ready.status -eq "ready") {
        Write-Host "正常に利用できます。" -ForegroundColor Green
    } else { Write-Host "一部の準備が完了していません。" -ForegroundColor Yellow }
} catch {
    Write-Host "現在は利用できません。起動ショートカットを実行してください。" -ForegroundColor Red
}
Read-Host "Enterキーで終了"
