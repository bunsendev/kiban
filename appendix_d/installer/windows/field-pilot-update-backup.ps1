param([Parameter(Mandatory = $true)][string]$DataRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.Recovery.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force

$mutex = [System.Threading.Mutex]::new($false, "Local\BunsenFieldPilotStart")
$locked = $false
try {
    try { $locked = $mutex.WaitOne(180000) }
    catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw "他の処理が完了しませんでした。" }
    $install = Get-FieldPilotInstall $DataRoot
    $archive = New-FieldPilotBackup $install -Trigger "pre-update"
    Write-Host "更新前Backupを検証しました: $archive" -ForegroundColor Green
} catch {
    try { Write-FieldPilotLog $DataRoot "backup_pre-update" "failed" } catch { }
    Write-Host "更新前Backupを完了できませんでした: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
