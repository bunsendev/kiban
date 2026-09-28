Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$base = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Bunsen\FieldPilot"))
$dataRoot = Join-Path $base "Data"
$appRoot = Join-Path $base "App"
$appFull = [System.IO.Path]::GetFullPath($appRoot)
$basePrefix = $base.TrimEnd("\") + "\"
if (-not $appFull.StartsWith($basePrefix, [StringComparison]::OrdinalIgnoreCase) -or
    $appFull -eq $base) {
    throw "アプリ削除先を安全に確認できませんでした。"
}
$installPath = Join-Path $dataRoot "install.json"
$activeApp = $null
if (Test-Path -LiteralPath $installPath) {
    $install = Get-Content -LiteralPath $installPath -Raw -Encoding utf8 | ConvertFrom-Json
    $activeApp = [System.IO.Path]::GetFullPath([string]$install.appRoot)
    if (-not $activeApp.StartsWith($appFull.TrimEnd("\") + "\",
        [StringComparison]::OrdinalIgnoreCase)) {
        throw "登録済みアプリの場所が不正です。"
    }
    $envPath = Join-Path $dataRoot "Config\pilot.env"
    $dockerBin = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin"
    if (Test-Path -LiteralPath $dockerBin) { $env:Path = "$dockerBin;$env:Path" }
    $dockerReady = $false
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        & docker info *> $null
        $dockerReady = $LASTEXITCODE -eq 0
    }
    if ((Test-Path -LiteralPath $envPath) -and $dockerReady) {
        & docker compose --project-name bunsen-field-pilot --env-file $envPath `
            -f (Join-Path $activeApp "compose.yaml") `
            -f (Join-Path $activeApp "compose.field-pilot.yaml") stop api postgres
        if ($LASTEXITCODE -ne 0) { throw "サービスを安全に停止できませんでした。" }
    }
}
$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
foreach ($name in @(
    "ブンセン 出荷予測", "ブンセン 出荷予測を終了", "ブンセン 出荷予測の状態確認",
    "ブンセン バックアップ作成", "ブンセン バックアップから復元",
    "ブンセン 本日の作業を完了", "ブンセン 改善データ接続設定",
    "ブンセン Feedback Server 接続テスト", "ブンセン 個別サポート送信"
)) {
    $shortcut = Join-Path $desktop ($name + ".lnk")
    if (Test-Path -LiteralPath $shortcut) {
        $item = $shell.CreateShortcut($shortcut)
        if ($item.Arguments -like "*Bunsen*FieldPilot*" -and
            $item.TargetPath -like "*powershell.exe") {
            Remove-Item -LiteralPath $shortcut
        }
    }
}
$folderShortcut = Join-Path $desktop "ブンセン データ投入.lnk"
if (Test-Path -LiteralPath $folderShortcut) {
    $item = $shell.CreateShortcut($folderShortcut)
    $expected = [System.IO.Path]::GetFullPath((Join-Path $dataRoot "Inbox\Drop"))
    if ([System.IO.Path]::GetFullPath($item.TargetPath) -eq $expected) {
        Remove-Item -LiteralPath $folderShortcut
    }
}
foreach ($scheme in @("bunsen-pilot-finish", "bunsen-pilot-connect")) {
    $key = "HKCU:\Software\Classes\$scheme"
    if (Test-Path -LiteralPath $key) {
        $commandKey = Join-Path $key "shell\open\command"
        $command = if (Test-Path -LiteralPath $commandKey) {
            (Get-Item -LiteralPath $commandKey).GetValue("")
        } else { "" }
        if ($activeApp -and $command -and $command.Contains($activeApp)) {
            Remove-Item -LiteralPath $key -Recurse -Force
        }
    }
}
if (Test-Path -LiteralPath $appFull) {
    # 再帰削除は専用Appの絶対pathだけに限定し、DataとDocker volumeは保持する。
    if (-not $appFull.StartsWith($basePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "削除先がField Pilot配下ではありません。"
    }
    Remove-Item -LiteralPath $appFull -Recurse -Force
}
Add-Content -LiteralPath (Join-Path $dataRoot "Logs\pilot.log") `
    -Value ("{0}`tuninstall`tapp_removed_data_preserved" -f (Get-Date).ToUniversalTime().ToString("o")) `
    -Encoding utf8
Write-Host "アプリを削除しました。PilotデータとDocker volumeは保持しています。"
