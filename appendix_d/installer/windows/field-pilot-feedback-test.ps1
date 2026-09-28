param([Parameter(Mandatory = $true)][string]$DataRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.Feedback.psm1") -Force

Add-Type -AssemblyName System.Windows.Forms
$choice = [System.Windows.Forms.MessageBox]::Show(
    "業務データを含まない接続テストを行いますか？", "ブンセン 接続テスト", "YesNo", "Question"
)
if ($choice -ne [System.Windows.Forms.DialogResult]::Yes) { return }
try {
    $install = Get-FieldPilotInstall $DataRoot
    $result = Invoke-FieldPilotFeedback $install "connection-test"
    $message = switch ($result.status) {
        "CONNECTED" { "サーバーとの接続に成功しました。" }
        "AUTH" { "認証情報を確認してください。" }
        "CLIENT_ID" { "Client IDを確認してください。" }
        "NETWORK" { "ネットワーク接続を確認してください。" }
        "PRIVACY_POLICY" { "共有範囲の設定を管理担当者へ確認してください。" }
        "LOCAL_ONLY" { "接続設定がありません。管理担当者へ確認してください。" }
        default { "サーバーから正常な応答を確認できませんでした。管理担当者へ確認してください。" }
    }
    Write-FieldPilotLog $install.DataRoot "feedback_connection_test" $result.status
    [System.Windows.Forms.MessageBox]::Show(
        $message, "ブンセン 接続テスト", "OK", "Information"
    ) | Out-Null
} catch {
    [System.Windows.Forms.MessageBox]::Show(
        "接続テストを完了できませんでした。管理担当者へ確認してください。",
        "ブンセン 接続テスト", "OK", "Warning"
    ) | Out-Null
    exit 1
}
