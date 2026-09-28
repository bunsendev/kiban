param(
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [string]$BundlePath
)
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
    if (-not $BundlePath) {
        Add-Type -AssemblyName System.Windows.Forms
        $picker = [System.Windows.Forms.OpenFileDialog]::new()
        $picker.Filter = "ブンセン復旧ZIP (*.zip)|*.zip"
        $picker.Title = "復元するバックアップを選択"
        if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return }
        $BundlePath = $picker.FileName
    }
    $answer = Read-Host "現在のデータを事前保存して復元します。続ける場合は RESTORE と入力"
    if ($answer -cne "RESTORE") { Write-Host "中止しました。"; return }
    $install = Get-FieldPilotInstall $DataRoot
    Restore-FieldPilotBackup $install $BundlePath
    Write-Host "復元し、起動確認が完了しました。" -ForegroundColor Green
} catch {
    Write-Host "復元できませんでした: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
