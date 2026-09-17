Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-KibanRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Test-KibanPackageIntegrity {
    $root = Get-KibanRoot
    $manifestPath = Join-Path $root "SHA256SUMS.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        throw "配布ファイルの検証情報がありません。ZIPをもう一度展開してください。"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
    foreach ($property in $manifest.PSObject.Properties) {
        $path = Join-Path $root ($property.Name.Replace("/", "\"))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "配布ファイルが不足しています。ZIPをもう一度展開してください。"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne ([string]$property.Value).ToLowerInvariant()) {
            throw "配布ファイルが変更されています。ZIPをもう一度展開してください。"
        }
    }
}

function Test-Command([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function New-LocalToken {
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

function Initialize-KibanDirectories {
    $root = Get-KibanRoot
    @(
        ".kiban", "snapshot_input", "report_output", "import_input",
        "mapping_dry_run_output", "raw_archive"
    ) | ForEach-Object {
        New-Item -ItemType Directory -Force -Path (Join-Path $root $_) | Out-Null
    }
}

function Initialize-KibanEnvironment {
    $root = Get-KibanRoot
    $environmentPath = Join-Path $root ".env"
    if (-not (Test-Path -LiteralPath $environmentPath)) {
        $token = New-LocalToken
        @(
            "KIBAN_API_TOKEN=$token"
            "KIBAN_API_SUBJECT=local-operator"
        ) | Set-Content -LiteralPath $environmentPath -Encoding ascii
    }
    $httpPort = Initialize-KibanHttpPort
    $tokenLine = Get-Content -LiteralPath $environmentPath |
        Where-Object { $_ -like "KIBAN_API_TOKEN=*" } |
        Select-Object -First 1
    if (-not $tokenLine) { throw ".envにKIBAN_API_TOKENがありません。" }
    $token = $tokenLine.Substring("KIBAN_API_TOKEN=".Length)
    $connectionPath = Join-Path $root ".kiban\接続情報.txt"
    @(
        "データ準備・検証画面"
        "http://127.0.0.1:$httpPort/ui/intake"
        ""
        "予測OSS分析画面"
        "http://127.0.0.1:$httpPort/ui/analysis"
        ""
        "接続コード"
        $token
        ""
        "この接続コードをメールやチャットへ貼り付けないでください。"
    ) | Set-Content -LiteralPath $connectionPath -Encoding utf8
    return $connectionPath
}

function Test-KibanTcpPort([int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        $listener.Stop()
    }
}

function Initialize-KibanHttpPort {
    $environmentPath = Join-Path (Get-KibanRoot) ".env"
    $existing = Get-Content -LiteralPath $environmentPath -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^KIBAN_HTTP_PORT=([0-9]+)$" } |
        Select-Object -First 1
    if ($existing) { return [int]$existing.Substring("KIBAN_HTTP_PORT=".Length) }
    $candidates = @(58000) + @(48100..48120)
    $port = $candidates | Where-Object { Test-KibanTcpPort $_ } | Select-Object -First 1
    if (-not $port) { throw "予測基盤で使用できるローカルportがありません。" }
    Add-Content -LiteralPath $environmentPath -Value "KIBAN_HTTP_PORT=$port" -Encoding ascii
    return [int]$port
}

function Get-KibanHttpPort {
    $environmentPath = Join-Path (Get-KibanRoot) ".env"
    $line = Get-Content -LiteralPath $environmentPath -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^KIBAN_HTTP_PORT=([0-9]+)$" } |
        Select-Object -First 1
    if (-not $line) { return 58000 }
    return [int]$line.Substring("KIBAN_HTTP_PORT=".Length)
}

function Get-KibanBaseUri {
    return "http://127.0.0.1:$(Get-KibanHttpPort)"
}

function Add-DockerPath {
    $dockerBin = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin"
    if (Test-Path -LiteralPath $dockerBin) { $env:Path = "$dockerBin;$env:Path" }
}

function Test-DockerEngine {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & docker info *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Wait-DockerEngine([int]$Seconds) {
    for ($attempt = 1; $attempt -le $Seconds; $attempt++) {
        if (Test-DockerEngine) { return $true }
        Start-Sleep -Seconds 1
        Write-Progress -Activity "Docker Desktopを起動しています" -Status "$attempt / ${Seconds}秒"
    }
    return $false
}

function Repair-DockerRuntimeSockets {
    if (Test-DockerEngine) { return }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        $runningDistributions = @(@(& wsl.exe --list --running --quiet 2>$null) |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { $_ -and $_ -ne "docker-desktop" })
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($runningDistributions.Count -gt 0) {
        throw "Docker以外のWSLが実行中のため自動復旧を中止しました。WSL作業を終了して再実行してください。"
    }
    Get-Process -Name "Docker Desktop", "com.docker.backend", "com.docker.build" `
        -ErrorAction SilentlyContinue | Stop-Process -Force
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & wsl.exe --terminate docker-desktop *> $null
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    Start-Sleep -Seconds 2
    $localRoot = [System.IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd("\") + "\"
    $stamp = Get-Date -Format "yyyyMMddHHmmss"
    $sources = @(
        (Join-Path $env:LOCALAPPDATA "Docker\run"),
        (Join-Path $env:LOCALAPPDATA "docker-secrets-engine")
    )
    foreach ($source in $sources) {
        if (-not (Test-Path -LiteralPath $source)) { continue }
        $sourcePath = [System.IO.Path]::GetFullPath($source)
        $targetPath = [System.IO.Path]::GetFullPath("$source.stale-$stamp")
        if (-not $sourcePath.StartsWith($localRoot, [StringComparison]::OrdinalIgnoreCase) -or
            -not $targetPath.StartsWith($localRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Docker runtime socketの退避先を安全に確認できませんでした。"
        }
        Move-Item -LiteralPath $sourcePath -Destination $targetPath
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $env:LOCALAPPDATA "Docker\run") |
        Out-Null
}

function Start-DockerDesktop {
    Add-DockerPath
    if ((Test-Command "docker") -and (Test-DockerEngine)) { return }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")
    )
    $desktop = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $desktop) { throw "Docker Desktopが見つかりません。" }
    Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null
    if (Wait-DockerEngine 90) { return }
    Write-Host "Docker runtimeを安全な退避フォルダーへ移して再起動します。" -ForegroundColor Yellow
    Repair-DockerRuntimeSockets
    Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null
    if (Wait-DockerEngine 120) { return }
    throw "Docker Desktopを起動できませんでした。状態確認を実行してください。"
}

function Invoke-KibanCompose([string[]]$Arguments) {
    $root = Get-KibanRoot
    Push-Location $root
    try {
        & docker compose @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Docker Composeの実行に失敗しました。" }
    } finally { Pop-Location }
}

function Wait-KibanReady([int]$Seconds = 120) {
    $baseUri = Get-KibanBaseUri
    for ($attempt = 1; $attempt -le $Seconds; $attempt++) {
        try {
            $ready = Invoke-RestMethod -Uri "$baseUri/ready" -TimeoutSec 3
            if ($ready.status -eq "ready") { return }
        } catch { }
        Start-Sleep -Seconds 1
        Write-Progress -Activity "予測基盤を準備しています" -Status "$attempt / ${Seconds}秒"
    }
    throw "予測基盤の準備が時間内に完了しませんでした。状態確認を実行してください。"
}

function Open-KibanUi {
    Start-Process "$(Get-KibanBaseUri)/ui/intake"
}

function Install-KibanShortcuts {
    $root = Get-KibanRoot
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $items = @(
        @{ Name = "予測基盤を起動"; Target = "予測基盤を起動.cmd" },
        @{ Name = "予測OSS分析を起動"; Target = "予測OSS分析を起動.cmd" },
        @{ Name = "TimesFM分析を追加起動"; Target = "TimesFM分析を追加起動.cmd" },
        @{ Name = "予測基盤を停止"; Target = "予測基盤を停止.cmd" },
        @{ Name = "予測基盤の状態確認"; Target = "状態確認.cmd" }
    )
    foreach ($item in $items) {
        $shortcut = $shell.CreateShortcut((Join-Path $desktop "$($item.Name).lnk"))
        $shortcut.TargetPath = Join-Path $root $item.Target
        $shortcut.WorkingDirectory = $root
        $shortcut.Save()
    }
}

Export-ModuleMember -Function *
