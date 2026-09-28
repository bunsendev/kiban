param([Parameter(Mandatory = $true)][string]$DataRoot, [switch]$RotatePseudonymKey)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.Feedback.psm1") -Force

try {
    $install = Get-FieldPilotInstall $DataRoot
    $clientId = (Read-Host "Client ID［BUNSEN-PILOT-01］").Trim()
    $endpoint = (Read-Host "HTTPS送信先URL［https://bun.stock-tools.tech/upload.php］").Trim()
    if (-not $clientId) { $clientId = "BUNSEN-PILOT-01" }
    if (-not $endpoint) { $endpoint = "https://bun.stock-tools.tech/upload.php" }
    $keyFile = (Read-Host "中央公開鍵 PEM の保存先").Trim()
    $updateUrl = (Read-Host "署名済み更新ManifestのHTTPS URL（未設定なら空欄）").Trim()
    $updateKey = if ($updateUrl) {
        (Read-Host "更新署名の公開鍵 PEM の保存先").Trim()
    } else { "" }
    $secureToken = Read-Host "中央から通知された送信用Token" -AsSecureString
    $uri = [Uri]$endpoint
    if ($uri.Scheme -ne "https" -or -not $uri.Host -or
        $clientId -notmatch '^[A-Za-z0-9_-]{1,80}$' -or
        -not (Test-Path -LiteralPath $keyFile -PathType Leaf)) {
        throw "接続設定を確認してください。"
    }
    if ($updateUrl -and (([Uri]$updateUrl).Scheme -ne "https" -or
        -not (Test-Path -LiteralPath $updateKey -PathType Leaf))) {
        throw "更新確認の設定を確認してください。"
    }
    $token = (New-Object System.Management.Automation.PSCredential("feedback", $secureToken)).GetNetworkCredential().Password
    if ($token.Length -lt 32) { throw "Tokenを確認してください。" }
    $existing = Get-FeedbackCredentials $install
    if ($existing -and -not $RotatePseudonymKey) {
        $secret = ($existing | ConvertFrom-Json).hmac_secret_hex
    } else {
        $random = New-Object byte[] 32
        $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $generator.GetBytes($random) } finally { $generator.Dispose() }
        $secret = -join ($random | ForEach-Object { $_.ToString("x2") })
    }
    if ($secret -notmatch '^[0-9a-f]{64}$') { throw "疑似ID用の鍵を確認してください。" }
    $config = Join-Path $install.DataRoot "Config"
    $secrets = Join-Path $install.DataRoot "Secrets"
    New-Item -ItemType Directory -Force -Path $secrets | Out-Null
    Copy-Item -LiteralPath $keyFile -Destination (Join-Path $config "feedback-server-public.pem") -Force
    $clientConfig = @{
        client_id = $clientId
        endpoint = $endpoint
        transport = "shared_php"
        public_key_file = "/var/lib/kiban/pilot/feedback-server-public.pem"
    }
    if ($updateUrl) {
        Copy-Item -LiteralPath $updateKey -Destination (Join-Path $config "feedback-update-public.pem") -Force
        $clientConfig.update_manifest_url = $updateUrl
        $clientConfig.update_signing_key_file = "/var/lib/kiban/pilot/feedback-update-public.pem"
    }
    $clientConfig | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $config "feedback-client.json") -Encoding utf8
    $credentialJson = [pscustomobject]@{
        hmac_secret_hex = $secret
        bearer_token = $token
    } | ConvertTo-Json -Compress
    $protected = ConvertTo-SecureString $credentialJson -AsPlainText -Force | ConvertFrom-SecureString
    Set-Content -LiteralPath (Join-Path $secrets "feedback-credentials.dpapi") `
        -Value $protected -Encoding ascii
    Write-FieldPilotLog $install.DataRoot "feedback_config" "completed"
    Write-Host "接続設定を保存しました。共有範囲は管理画面で明示設定するまで送信OFFです。"
} catch {
    try { Write-FieldPilotLog $DataRoot "feedback_config" "failed" } catch { }
    Write-Host "接続設定を完了できませんでした。管理担当者へ確認してください。" -ForegroundColor Red
    exit 1
}
