Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force

function Get-FeedbackCredentials($Install) {
    $path = Join-Path $Install.DataRoot "Secrets\feedback-credentials.dpapi"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    $encrypted = Get-Content -LiteralPath $path -Raw -Encoding utf8
    $secure = ConvertTo-SecureString $encrypted
    $credential = New-Object System.Management.Automation.PSCredential("feedback", $secure)
    return $credential.GetNetworkCredential().Password
}

function Invoke-FieldPilotFeedback($Install, [ValidateSet("finish", "retry", "support", "connection-test")]
    [string]$Action, [string]$SupportFile = "", [string]$ConsentId = "") {
    $configPath = Join-Path $Install.DataRoot "Config\feedback-client.json"
    $credentials = Get-FeedbackCredentials $Install
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf) -or -not $credentials) {
        return [pscustomobject]@{ status = "LOCAL_ONLY"; sent = 0; retryable = 0; rejected = 0 }
    }
    Add-DockerPath
    $envPath = Join-Path $Install.DataRoot "Config\pilot.env"
    $arguments = @(
        "compose", "--project-name", "bunsen-field-pilot", "--env-file", $envPath,
        "-f", (Join-Path $Install.AppRoot "compose.yaml"),
        "-f", (Join-Path $Install.AppRoot "compose.field-pilot.yaml"),
        "run", "--rm", "-T", "--no-deps", "api", "python", "-m",
        "forecast_provider.feedback_sync.client", "--inbox-root", "/var/lib/kiban/pilot-inbox",
        "--client-config", "/var/lib/kiban/pilot/feedback-client.json",
        "--settings-root", "/var/lib/kiban/pilot-settings",
        "--action", $Action
    )
    if ($Action -eq "support") {
        if (-not $SupportFile -or -not $ConsentId) { throw "個別許可と対象ファイルが必要です。" }
        $arguments += @("--support-file", $SupportFile, "--consent-id", $ConsentId)
    }
    $output = $credentials | & docker @arguments
    if ($LASTEXITCODE -ne 0) { throw "改善データの送信準備を完了できませんでした。" }
    return $output | Select-Object -Last 1 | ConvertFrom-Json
}

Export-ModuleMember -Function Get-FeedbackCredentials, Invoke-FieldPilotFeedback
