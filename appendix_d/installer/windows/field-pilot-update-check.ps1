param([Parameter(Mandatory = $true)][string]$DataRoot,
      [ValidateSet("STARTUP", "END_OF_DAY")][string]$Trigger = "STARTUP")
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force

try {
    $install = Get-FieldPilotInstall $DataRoot
    Invoke-FieldPilotCompose $install @(
        "exec", "-T", "api", "python", "-m",
        "forecast_provider.update_service.check_cli", "--trigger", $Trigger
    ) | Out-Null
    Write-FieldPilotLog $install.DataRoot "update_check" "completed"
} catch {
    try { Write-FieldPilotLog $DataRoot "update_check" "failed" } catch { }
    # 更新側の障害で現場の開始・終業処理を止めない。
}
