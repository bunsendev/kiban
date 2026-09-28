param([Parameter(Mandatory = $true)][string]$DataRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.Feedback.psm1") -Force

$mutex = [System.Threading.Mutex]::new($false, "Local\BunsenFieldPilotStart")
$locked = $false
$stage = $null
try {
    try { $locked = $mutex.WaitOne(180000) }
    catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw "ほかの処理が完了しませんでした。" }
    $install = Get-FieldPilotInstall $DataRoot
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Filter = "CSVまたはPDF (*.csv;*.pdf)|*.csv;*.pdf"
    $picker.Title = "個別許可した原本を選択"
    if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return }
    $source = Get-Item -LiteralPath $picker.FileName
    if ($source.Attributes -band [IO.FileAttributes]::ReparsePoint -or
        $source.Length -gt 5000000 -or $source.Length -le 0) {
        throw "対象ファイルを確認してください。"
    }
    $consentId = (Read-Host "管理画面に表示された個別許可ID").Trim()
    if ($consentId -notmatch '^[0-9a-f]{32}$') { throw "個別許可IDを確認してください。" }
    $config = Get-Content -LiteralPath (Join-Path $install.DataRoot "Config\feedback-client.json") `
        -Raw -Encoding utf8 | ConvertFrom-Json
    $message = "対象: $($source.Name)`n送信先: $($config.endpoint)`n今回だけ送信しますか？"
    $choice = [System.Windows.Forms.MessageBox]::Show(
        $message, "ブンセン サポート送信", "YesNo", "Warning"
    )
    if ($choice -ne [System.Windows.Forms.DialogResult]::Yes) { return }
    $root = [IO.Path]::GetFullPath((Join-Path $install.DataRoot "Inbox\SupportStage"))
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $stageName = [guid]::NewGuid().ToString("N")
    $stage = [IO.Path]::GetFullPath((Join-Path $root $stageName))
    if (-not $stage.StartsWith($root.TrimEnd("\") + "\",
        [StringComparison]::OrdinalIgnoreCase)) { throw "一時保存先が不正です。" }
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-Item -LiteralPath $source.FullName -Destination (Join-Path $stage $source.Name)
    $containerPath = "/var/lib/kiban/pilot-inbox/SupportStage/$stageName/$($source.Name)"
    $result = Invoke-FieldPilotFeedback $install "support" -SupportFile $containerPath `
        -ConsentId $consentId
    if ($result.rejected -gt 0) { throw "中央側の個別許可を確認してください。" }
    Write-Host "個別送信を処理しました。状態: $($result.package_id)"
} catch {
    try { Write-FieldPilotLog $DataRoot "support_send" "failed" } catch { }
    Write-Host "個別送信できませんでした。管理担当者へ確認してください。" -ForegroundColor Red
    exit 1
} finally {
    if ($stage -and (Test-Path -LiteralPath $stage)) {
        $root = [IO.Path]::GetFullPath((Join-Path $DataRoot "Inbox\SupportStage"))
        $checked = [IO.Path]::GetFullPath($stage)
        if ($checked.StartsWith($root.TrimEnd("\") + "\",
            [StringComparison]::OrdinalIgnoreCase) -and
            -not ((Get-Item -LiteralPath $checked).Attributes -band
            [IO.FileAttributes]::ReparsePoint)) {
            Remove-Item -LiteralPath $checked -Recurse -Force
        }
    }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
