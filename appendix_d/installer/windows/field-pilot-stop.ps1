param([Parameter(Mandatory = $true)][string]$DataRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force

try {
    $install = Get-FieldPilotInstall $DataRoot
    Add-DockerPath
    if (Test-DockerEngine) {
        Invoke-FieldPilotCompose $install @("stop", "pilot-inventory-worker", "api", "postgres")
    }
    Write-FieldPilotLog $install.DataRoot "stop" "completed"
} catch {
    try { Write-FieldPilotLog $DataRoot "stop" "failed" } catch { }
    Show-FieldPilotError "終了できませんでした。管理担当者へご連絡ください。"
    exit 1
}
