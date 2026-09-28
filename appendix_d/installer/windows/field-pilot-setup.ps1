Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force

function Assert-UnderDirectory([string]$Path, [string]$Directory) {
    $root = [System.IO.Path]::GetFullPath($Directory).TrimEnd("\") + "\"
    $target = [System.IO.Path]::GetFullPath($Path)
    if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "配布ファイルの配置先が不正です。"
    }
}

function Copy-FieldPilotPackage([string]$SourceRoot, [string]$AppBase) {
    $manifestPath = Join-Path $SourceRoot "SHA256SUMS.json"
    $fingerprint = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $appRoot = Join-Path $AppBase $fingerprint.Substring(0, 20)
    Assert-UnderDirectory $appRoot $AppBase
    if (Test-Path -LiteralPath (Join-Path $appRoot "SHA256SUMS.json")) {
        return $appRoot
    }
    if (Test-Path -LiteralPath $appRoot) {
        throw "同じ版のアプリ配置が不完全です。管理担当者へ連絡してください。"
    }
    $staging = Join-Path $AppBase (".staging-" + [guid]::NewGuid().ToString("N"))
    Assert-UnderDirectory $staging $AppBase
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
    foreach ($property in $manifest.PSObject.Properties) {
        $relative = [string]$property.Name
        $source = Join-Path $SourceRoot $relative
        $destination = Join-Path $staging $relative
        Assert-UnderDirectory $source $SourceRoot
        Assert-UnderDirectory $destination $staging
        $parent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
    }
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $staging "SHA256SUMS.json")
    # Directory全体を動かす前に、移動元と移動先が専用App配下であることを確認する。
    Assert-UnderDirectory $staging $AppBase
    Assert-UnderDirectory $appRoot $AppBase
    Move-Item -LiteralPath $staging -Destination $appRoot
    return $appRoot
}

function New-FieldPilotEnvironment([string]$DataRoot) {
    $config = Join-Path $DataRoot "Config"
    $path = Join-Path $config "pilot.env"
    $inboxMount = (Join-Path $DataRoot "Inbox").Replace("\", "/")
    $settingsMount = (Join-Path $DataRoot "LocalSettings").Replace("\", "/")
    $backupMount = (Join-Path $DataRoot "Backup").Replace("\", "/")
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        if (-not (Select-String -LiteralPath $path -Pattern '^KIBAN_FIELD_PILOT_INBOX_DIR=' -Quiet)) {
            Add-Content -LiteralPath $path -Value "KIBAN_FIELD_PILOT_INBOX_DIR=$inboxMount" -Encoding ascii
        }
        if (-not (Select-String -LiteralPath $path -Pattern '^KIBAN_FIELD_PILOT_SETTINGS_DIR=' -Quiet)) {
            Add-Content -LiteralPath $path -Value "KIBAN_FIELD_PILOT_SETTINGS_DIR=$settingsMount" -Encoding ascii
        }
        if (-not (Select-String -LiteralPath $path -Pattern '^KIBAN_FIELD_PILOT_BACKUP_DIR=' -Quiet)) {
            Add-Content -LiteralPath $path -Value "KIBAN_FIELD_PILOT_BACKUP_DIR=$backupMount" -Encoding ascii
        }
        if (-not (Select-String -LiteralPath $path -Pattern '^KIBAN_FIELD_PILOT_LEARNING_ADMIN_TOKEN=' -Quiet)) {
            Add-Content -LiteralPath $path -Value "KIBAN_FIELD_PILOT_LEARNING_ADMIN_TOKEN=$(New-LocalToken)" -Encoding ascii
        }
        if (-not (Select-String -LiteralPath $path -Pattern '^KIBAN_FIELD_PILOT_OPERATOR_ID=' -Quiet)) {
            $operator = ($env:USERNAME -replace '[^A-Za-z0-9_.-]', '_')
            Add-Content -LiteralPath $path -Value "KIBAN_FIELD_PILOT_OPERATOR_ID=WINDOWS:$operator" -Encoding ascii
        }
        return
    }
    $httpPort = @(48130..48159) | Where-Object { Test-KibanTcpPort $_ } | Select-Object -First 1
    $databasePort = @(55440..55469) | Where-Object { Test-KibanTcpPort $_ } | Select-Object -First 1
    if (-not $httpPort -or -not $databasePort) { throw "ローカル通信portを確保できません。" }
    $snapshot = (Join-Path $DataRoot "Input").Replace("\", "/")
    $reports = (Join-Path $DataRoot "Reports").Replace("\", "/")
    $mapping = (Join-Path $DataRoot "Mapping").Replace("\", "/")
    $imports = (Join-Path $DataRoot "Import").Replace("\", "/")
    $configMount = $config.Replace("\", "/")
    @(
        "KIBAN_HTTP_PORT=$httpPort"
        "KIBAN_POSTGRES_PORT=$databasePort"
        "KIBAN_API_TOKEN=$(New-LocalToken)"
        "KIBAN_FIELD_PILOT_DB_PASSWORD=$(New-LocalToken)"
        "KIBAN_SNAPSHOT_DIR=$snapshot"
        "KIBAN_REPORT_DIR=$reports"
        "KIBAN_MAPPING_DRY_RUN_DIR=$mapping"
        "KIBAN_IMPORT_DIR=$imports"
        "KIBAN_FIELD_PILOT_CONFIG_DIR=$configMount"
        "KIBAN_FIELD_PILOT_INBOX_DIR=$inboxMount"
        "KIBAN_FIELD_PILOT_SETTINGS_DIR=$settingsMount"
        "KIBAN_FIELD_PILOT_BACKUP_DIR=$backupMount"
        "KIBAN_FIELD_PILOT_LEARNING_ADMIN_TOKEN=$(New-LocalToken)"
        "KIBAN_FIELD_PILOT_OPERATOR_ID=WINDOWS:$(($env:USERNAME -replace '[^A-Za-z0-9_.-]', '_'))"
    ) | Set-Content -LiteralPath $path -Encoding ascii
}

function Install-FieldPilotShortcuts([string]$AppRoot, [string]$DataRoot) {
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $items = @(
        @{ Name = "ブンセン 出荷予測"; Script = "field-pilot-start.ps1" },
        @{ Name = "ブンセン 出荷予測を終了"; Script = "field-pilot-stop.ps1" },
        @{ Name = "ブンセン 出荷予測の状態確認"; Script = "field-pilot-status.ps1" },
        @{ Name = "ブンセン バックアップ作成"; Script = "field-pilot-backup.ps1"; Visible = $true },
        @{ Name = "ブンセン バックアップから復元"; Script = "field-pilot-restore.ps1"; Visible = $true },
        @{ Name = "ブンセン 本日の作業を完了"; Script = "field-pilot-finish.ps1"; Visible = $true },
        @{ Name = "ブンセン 改善データ接続設定"; Script = "field-pilot-feedback-configure.ps1"; Visible = $true },
        @{ Name = "ブンセン 個別サポート送信"; Script = "field-pilot-support-send.ps1"; Visible = $true }
    )
    foreach ($item in $items) {
        $scriptPath = Join-Path $AppRoot ("installer\windows\" + $item.Script)
        $shortcut = $shell.CreateShortcut((Join-Path $desktop ($item.Name + ".lnk")))
        $shortcut.TargetPath = $powershell
        $windowStyle = if ($item.ContainsKey("Visible")) { "Normal" } else { "Hidden" }
        $stayOpen = if ($item.ContainsKey("Visible")) { "-NoExit " } else { "" }
        $arguments = "-NoProfile ${stayOpen}-ExecutionPolicy Bypass -WindowStyle $windowStyle -File `"$scriptPath`" -DataRoot `"$DataRoot`""
        $shortcut.Arguments = $arguments
        $shortcut.WorkingDirectory = $AppRoot
        $shortcut.Save()
    }
    $folder = $shell.CreateShortcut((Join-Path $desktop "ブンセン データ投入.lnk"))
    $folder.TargetPath = Join-Path $DataRoot "Inbox\Drop"
    $folder.Save()
}

try {
    Write-Host "[1/6] 配布ファイルを照合しています..."
    Test-KibanPackageIntegrity
    $sourceRoot = Get-KibanRoot
    if ([Environment]::OSVersion.Version.Major -lt 10 -or
        -not [Environment]::Is64BitOperatingSystem) {
        throw "64 bitの対応Windowsが必要です。"
    }
    Write-Host "[2/6] WSL 2とDocker Desktopを確認しています..."
    & wsl.exe --status *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "WSL 2が利用できません。PC管理者に有効化と再起動を依頼してください。"
    }
    Add-DockerPath
    if (-not (Test-Command "docker")) {
        if (-not (Test-Command "winget")) {
            throw "Docker Desktopが見つかりません。PC管理者に導入を依頼してください。"
        }
        Write-Host "Docker Desktopの社内利用条件を確認済みの場合のみ導入してください。"
        & winget install --exact --id Docker.DockerDesktop --scope user `
            --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Docker Desktopを導入できませんでした。" }
        Add-DockerPath
        if (-not (Test-Command "docker")) {
            throw "Docker Desktopを導入しました。PCを再起動してセットアップを再実行してください。"
        }
    }
    $base = Get-FieldPilotBase
    $appBase = Join-Path $base "App"
    $dataRoot = Join-Path $base "Data"
    Write-Host "[3/6] アプリとデータの保存先を準備しています..."
    foreach ($path in @($appBase, $dataRoot, (Join-Path $dataRoot "Config"),
        (Join-Path $dataRoot "Input"), (Join-Path $dataRoot "Reports"),
        (Join-Path $dataRoot "Mapping"), (Join-Path $dataRoot "Import"),
        (Join-Path $dataRoot "LocalSettings"), (Join-Path $dataRoot "Backup"),
        (Join-Path $dataRoot "Secrets"),
        (Join-Path $dataRoot "Logs"), (Join-Path $dataRoot "Tools"),
        (Join-Path $dataRoot "Inbox\Drop"), (Join-Path $dataRoot "Inbox\Staged"),
        (Join-Path $dataRoot "Inbox\Archive"), (Join-Path $dataRoot "Inbox\Observed"))) {
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
    $appRoot = Copy-FieldPilotPackage $sourceRoot $appBase
    $settings = Join-Path $dataRoot "Config\pilot-settings.json"
    if (-not (Test-Path -LiteralPath $settings)) {
        Copy-Item -LiteralPath (Join-Path $appRoot "installer\windows\pilot-settings.example.json") `
            -Destination $settings
    }
    $inboxPolicy = Join-Path $dataRoot "Config\inbox-policy.json"
    if (-not (Test-Path -LiteralPath $inboxPolicy)) {
        Copy-Item -LiteralPath (Join-Path $appRoot "installer\windows\inbox-policy.example.json") `
            -Destination $inboxPolicy
    }
    $recoveryPolicy = Join-Path $dataRoot "Config\recovery-policy.json"
    if (-not (Test-Path -LiteralPath $recoveryPolicy)) {
        Copy-Item -LiteralPath (Join-Path $appRoot "installer\windows\recovery-policy.example.json") `
            -Destination $recoveryPolicy
    }
    New-FieldPilotEnvironment $dataRoot
    Copy-Item -LiteralPath (Join-Path $appRoot "installer\windows\field-pilot-uninstall.ps1") `
        -Destination (Join-Path $dataRoot "Tools\field-pilot-uninstall.ps1") -Force
    $environment = Get-Content -LiteralPath (Join-Path $dataRoot "Config\pilot.env")
    $portLine = $environment | Where-Object { $_ -match '^KIBAN_HTTP_PORT=[0-9]+$' } |
        Select-Object -First 1
    if (-not $portLine) { throw "Field Pilotの通信設定が不正です。" }
    $port = [int]$portLine.Substring("KIBAN_HTTP_PORT=".Length)
    [pscustomobject]@{
        appRoot = $appRoot
        port = $port
        installedAt = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataRoot "install.json") -Encoding utf8
    Install-FieldPilotShortcuts $appRoot $dataRoot
    Write-FieldPilotLog $dataRoot "install" "completed"
    Write-Host "[4/6] Docker Desktopを起動しています..."
    Start-DockerDesktop
    $install = Get-FieldPilotInstall $dataRoot
    Write-Host "[5/6] Field Pilotを起動しています..."
    Invoke-FieldPilotCompose $install @("up", "-d", "--build", "postgres", "api")
    Wait-FieldPilotReady $install
    Invoke-FieldPilotInboxScan $install
    Write-Host "[6/6] 現場画面を開きます..."
    Open-FieldPilot $install
    $view = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/field-pilot/view" -TimeoutSec 5
    if ($view.status -ne "READY") {
        Write-Host "画面は起動しました。Pilotデータの確認・設定は管理担当者が行ってください。" -ForegroundColor Yellow
    }
    Write-Host "Field Pilotの導入が完了しました。" -ForegroundColor Green
} catch {
    try { Write-FieldPilotLog (Join-Path (Get-FieldPilotBase) "Data") "install" "failed" } catch { }
    Write-Host "導入を完了できませんでした。管理担当者へご連絡ください。" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
