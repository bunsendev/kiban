Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-FieldPilotBase {
    return Join-Path $env:LOCALAPPDATA "Bunsen\FieldPilot"
}

function Get-FieldPilotInstall([string]$DataRoot) {
    $base = [System.IO.Path]::GetFullPath((Get-FieldPilotBase)).TrimEnd("\") + "\"
    $dataPath = [System.IO.Path]::GetFullPath($DataRoot)
    if (-not $dataPath.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Field Pilotの保存先が不正です。"
    }
    $path = Join-Path $dataPath "install.json"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Field Pilotのインストール情報がありません。"
    }
    $install = Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json
    $appBase = [System.IO.Path]::GetFullPath((Join-Path (Get-FieldPilotBase) "App")).TrimEnd("\") + "\"
    $appRoot = [System.IO.Path]::GetFullPath([string]$install.appRoot)
    if (-not $appRoot.StartsWith($appBase, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath (Join-Path $appRoot "compose.field-pilot.yaml") -PathType Leaf)) {
        throw "Field Pilotのアプリ本体が見つかりません。"
    }
    return [pscustomobject]@{
        AppRoot = $appRoot
        DataRoot = $dataPath
        Port = [int]$install.port
        InstalledAt = [string]$install.installedAt
    }
}

function Write-FieldPilotLog([string]$DataRoot, [string]$Event, [string]$Status) {
    $logDir = Join-Path $DataRoot "Logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $line = "{0}`t{1}`t{2}" -f (Get-Date).ToUniversalTime().ToString("o"), $Event, $Status
    Add-Content -LiteralPath (Join-Path $logDir "pilot.log") -Value $line -Encoding utf8
}

function Invoke-FieldPilotCompose($Install, [string[]]$Arguments) {
    Add-DockerPath
    $envPath = Join-Path $Install.DataRoot "Config\pilot.env"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        throw "Field Pilotの接続設定がありません。"
    }
    & docker compose --project-name bunsen-field-pilot --env-file $envPath `
        -f (Join-Path $Install.AppRoot "compose.yaml") `
        -f (Join-Path $Install.AppRoot "compose.field-pilot.yaml") @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Field Pilotのサービスを操作できませんでした。" }
}

function Test-FieldPilotReady($Install) {
    try {
        $baseUri = "http://127.0.0.1:$($Install.Port)"
        $ready = Invoke-RestMethod -Uri "$baseUri/ready" -TimeoutSec 3
        if ($ready.status -ne "ready") { return $false }
        $view = Invoke-RestMethod -Uri "$baseUri/api/field-pilot/view" -TimeoutSec 3
        return $view.mode -eq "SHADOW" -and $view.read_only -eq $true
    } catch { return $false }
}

function Wait-FieldPilotReady($Install, [int]$Seconds = 180) {
    for ($attempt = 1; $attempt -le $Seconds; $attempt++) {
        if (Test-FieldPilotReady $Install) { return }
        Start-Sleep -Seconds 1
    }
    throw "Field Pilotの起動準備が完了しませんでした。"
}

function Open-FieldPilot($Install) {
    Start-Process "http://127.0.0.1:$($Install.Port)/ui/pilot" | Out-Null
}

function Invoke-FieldPilotInboxScan($Install) {
    & (Join-Path $Install.AppRoot "installer\windows\field-pilot-inbox-stage.ps1") `
        -DataRoot $Install.DataRoot
    Invoke-FieldPilotCompose $Install @(
        "exec", "-T", "api", "python", "-m", "forecast_provider.field_pilot.inbox_cli",
        "--inbox-root", "/var/lib/kiban/pilot-inbox",
        "--policy", "/var/lib/kiban/pilot/inbox-policy.json"
    )
    Write-FieldPilotLog $Install.DataRoot "inbox_scan" "completed"
}

function Show-FieldPilotError([string]$Message) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        $Message, "ブンセン 出荷予測", "OK", "Warning"
    ) | Out-Null
}

Export-ModuleMember -Function Get-FieldPilotBase, Get-FieldPilotInstall, `
    Write-FieldPilotLog, Invoke-FieldPilotCompose, Test-FieldPilotReady, `
    Wait-FieldPilotReady, Open-FieldPilot, Show-FieldPilotError, Invoke-FieldPilotInboxScan
