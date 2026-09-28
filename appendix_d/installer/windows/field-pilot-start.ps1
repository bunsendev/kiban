param([Parameter(Mandatory = $true)][string]$DataRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.Recovery.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.Feedback.psm1") -Force

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
        Invoke-FieldPilotCompose $install @("up", "-d", "postgres", "api", "pilot-inventory-worker")
        Wait-FieldPilotReady $install
    }
    Invoke-FieldPilotCompose $install @("up", "-d", "pilot-inventory-worker")
    $today = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")
    $backupDirectory = Join-Path $install.DataRoot "Backup"
    $daily = @(Get-ChildItem -LiteralPath $backupDirectory -File `
        -Filter "recovery-daily-$today-*.zip" -ErrorAction SilentlyContinue)
    if ($daily.Count -eq 0) {
        New-FieldPilotBackup $install -Trigger "daily" | Out-Null
    }
    Invoke-FieldPilotInboxScan $install
    Write-FieldPilotLog $install.DataRoot "start" "ready"
    Open-FieldPilot $install
    $retryScript = Join-Path $install.AppRoot "installer\windows\field-pilot-feedback-retry.ps1"
    $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    Start-Process -FilePath $powershell -WindowStyle Hidden -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        ('"' + $retryScript + '"'), "-DataRoot", ('"' + $install.DataRoot + '"')
    ) | Out-Null
    Write-FieldPilotLog $install.DataRoot "shadow_view" "opened"
} catch {
    try { Write-FieldPilotLog $DataRoot "start" "failed" } catch { }
    Show-FieldPilotError "起動準備に問題があります。管理担当者へご連絡ください。"
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
