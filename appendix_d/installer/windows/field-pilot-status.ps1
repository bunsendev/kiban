param([Parameter(Mandatory = $true)][string]$DataRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force

try {
    $install = Get-FieldPilotInstall $DataRoot
    if (Test-FieldPilotReady $install) {
        $view = Invoke-RestMethod -Uri "http://127.0.0.1:$($install.Port)/api/field-pilot/view" -TimeoutSec 5
        $message = if ($view.status -eq "READY") {
            "試験運用の画面は利用できます。"
        } else {
            "画面は起動していますが、Pilotデータの準備が必要です。管理担当者へご連絡ください。"
        }
    } else { $message = "起動していません。デスクトップの起動アイコンを押してください。" }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($message, "ブンセン 出荷予測") | Out-Null
} catch {
    Show-FieldPilotError "状態を確認できません。管理担当者へご連絡ください。"
    exit 1
}
