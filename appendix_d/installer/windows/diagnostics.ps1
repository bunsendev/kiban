Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.Analysis.psm1") -Force

$root = Get-KibanRoot
$output = Join-Path ([Environment]::GetFolderPath("Desktop")) ("予測基盤_診断_{0}.txt" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("取得日時: $(Get-Date -Format o)")
$lines.Add("Windows: $([Environment]::OSVersion.VersionString)")
$lines.Add("64bit: $([Environment]::Is64BitOperatingSystem)")
try {
    $capacity = Get-KibanComputerCapacity
    $lines.Add("CPU threads: $($capacity.LogicalProcessors)")
    $lines.Add("RAM total/free GB: $($capacity.TotalMemoryGB) / $($capacity.FreeMemoryGB)")
    $lines.Add("Disk free GB: $($capacity.FreeDiskGB)")
} catch { $lines.Add("PC資源: 取得不可") }
$lines.Add("WSL:")
$lines.Add((& wsl.exe --status 2>&1 | Out-String))
Add-DockerPath
$lines.Add("Docker:")
$lines.Add((& docker version --format '{{.Client.Version}} / {{.Server.Version}}' 2>&1 | Out-String))
Push-Location $root
try {
    $lines.Add("Compose services:")
    $lines.Add((& docker compose ps --format json 2>&1 | Out-String))
} finally { Pop-Location }
$baseUri = Get-KibanBaseUri
foreach ($uri in @("$baseUri/health", "$baseUri/ready")) {
    try { $lines.Add("$uri`n$((Invoke-RestMethod $uri -TimeoutSec 5 | ConvertTo-Json -Depth 5 -Compress))") }
    catch { $lines.Add("$uri`n接続不可") }
}
$lines.Add("接続コード、CSV本文、行値、環境変数、container logは収集していません。")
$lines | Set-Content -LiteralPath $output -Encoding utf8
Write-Host "診断情報をデスクトップへ保存しました。" -ForegroundColor Green
Write-Host $output
Read-Host "Enterキーで終了"
