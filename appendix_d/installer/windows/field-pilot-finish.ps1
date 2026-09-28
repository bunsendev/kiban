param([Parameter(Mandatory = $true)][string]$DataRoot, [switch]$FromBrowser)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.Recovery.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.Feedback.psm1") -Force

$mutex = [System.Threading.Mutex]::new($false, "Local\BunsenFieldPilotStart")
$locked = $false
try {
    if ($FromBrowser) {
        Add-Type -AssemblyName System.Windows.Forms
        $choice = [System.Windows.Forms.MessageBox]::Show(
            "本日の作業を完了しますか？", "ブンセン 出荷予測", "YesNo", "Question"
        )
        if ($choice -ne [System.Windows.Forms.DialogResult]::Yes) { return }
    }
    try { $locked = $mutex.WaitOne(180000) }
    catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw "ほかの処理が完了しませんでした。" }
    $install = Get-FieldPilotInstall $DataRoot
    Invoke-FieldPilotInboxScan $install
    New-FieldPilotBackup $install -Trigger "manual" | Out-Null
    try {
        $result = Invoke-FieldPilotFeedback $install "finish"
    } catch {
        Write-FieldPilotLog $install.DataRoot "feedback_sync" "needs_admin"
        $result = [pscustomobject]@{ status = "NEEDS_ADMIN" }
    }
    Invoke-FieldPilotCompose $install @("stop", "api", "postgres") | Out-Null
    Write-FieldPilotLog $install.DataRoot "end_of_day" "completed"
    if ($result.status -eq "SAVED_FOR_RETRY") {
        Write-Host "本日の作業は完了しました。送信できなかったデータはPCに保存しました。次回再送します。"
    } elseif ($result.status -eq "NEEDS_ADMIN") {
        Write-Host "本日の作業は完了しました。改善データの送信設定を管理担当者へ確認してください。"
    } else {
        Write-Host "本日の作業は完了しました。"
    }
    if ($FromBrowser) {
        $message = if ($result.status -eq "SAVED_FOR_RETRY") {
            "本日の作業は完了しました。未送信データはPCに保存し、次回起動時に再送します。"
        } elseif ($result.status -eq "NEEDS_ADMIN") {
            "本日の作業は完了しました。送信設定は管理担当者へ確認してください。"
        } else { "本日の作業は完了しました。" }
        [System.Windows.Forms.MessageBox]::Show(
            $message, "ブンセン 出荷予測", "OK", "Information"
        ) | Out-Null
    }
} catch {
    try { Write-FieldPilotLog $DataRoot "end_of_day" "failed" } catch { }
    Write-Host "本日の作業を完了できませんでした。管理担当者へ連絡してください。" -ForegroundColor Red
    if ($FromBrowser) {
        Show-FieldPilotError "本日の作業を完了できませんでした。管理担当者へ連絡してください。"
    }
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
