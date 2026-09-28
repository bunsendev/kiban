param([Parameter(Mandatory = $true)][string]$DataRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.Feedback.psm1") -Force
$mutex = [System.Threading.Mutex]::new($false, "Local\BunsenFieldPilotStart")
$locked = $false
try {
    try { $locked = $mutex.WaitOne(180000) }
    catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw "別の処理を実行中です。" }
    $install = Get-FieldPilotInstall $DataRoot
    $result = Invoke-FieldPilotFeedback $install "retry"
    $status = if ($result.status -eq "LOCAL_ONLY") { "local_only" } elseif (
        $result.rejected -gt 0
    ) { "needs_admin" } elseif (
        $result.retryable -gt 0 -or $result.deferred -gt 0
    ) { "saved_for_retry" } else { "completed" }
    Write-FieldPilotLog $install.DataRoot "feedback_retry" $status
} catch {
    try { Write-FieldPilotLog $DataRoot "feedback_retry" "failed" } catch { }
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
