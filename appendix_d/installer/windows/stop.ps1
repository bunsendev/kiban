Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.Analysis.psm1") -Force

try {
    $arguments = @("stop") + @(Get-KibanManagedServices)
    Invoke-KibanCompose $arguments
    Write-Host "予測基盤を停止しました。保存済みデータは維持されています。" -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host "Enterキーで終了"
    exit 1
}
