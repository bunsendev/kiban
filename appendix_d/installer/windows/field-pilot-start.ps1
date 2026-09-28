param([Parameter(Mandatory = $true)][string]$DataRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force

$mutex = [System.Threading.Mutex]::new($false, "Local\BunsenFieldPilotStart")
$locked = $false
try {
    try { $locked = $mutex.WaitOne(180000) }
    catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw "起動処理が完了しませんでした。" }
    $install = Get-FieldPilotInstall $DataRoot
    Write-FieldPilotLog $install.DataRoot "start" "requested"
    if (-not (Test-FieldPilotReady $install)) {
        Start-DockerDesktop
        Invoke-FieldPilotCompose $install @("up", "-d", "postgres", "api")
        Wait-FieldPilotReady $install
    }
    Write-FieldPilotLog $install.DataRoot "start" "ready"
    Open-FieldPilot $install
    Write-FieldPilotLog $install.DataRoot "shadow_view" "opened"
} catch {
    try { Write-FieldPilotLog $DataRoot "start" "failed" } catch { }
    Show-FieldPilotError "起動準備に問題があります。管理担当者へご連絡ください。"
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
