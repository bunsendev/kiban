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
    $tokenLine = Get-Content -LiteralPath $environmentPath |
        Where-Object { $_ -like "KIBAN_API_TOKEN=*" } |
        Select-Object -First 1
    if (-not $tokenLine) { throw ".envにKIBAN_API_TOKENがありません。" }
    $token = $tokenLine.Substring("KIBAN_API_TOKEN=".Length)
    $connectionPath = Join-Path $root ".kiban\接続情報.txt"
    @(
        "予測基盤 操作画面"
        "http://127.0.0.1:58000/ui/intake"
        ""
        "接続コード"
        $token
        ""
        "この接続コードをメールやチャットへ貼り付けないでください。"
    ) | Set-Content -LiteralPath $connectionPath -Encoding utf8
    return $connectionPath
}

function Add-DockerPath {
    $dockerBin = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin"
    if (Test-Path -LiteralPath $dockerBin) { $env:Path = "$dockerBin;$env:Path" }
}

function Start-DockerDesktop {
    Add-DockerPath
    if (Test-Command "docker") {
        & docker info *> $null
        if ($LASTEXITCODE -eq 0) { return }
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")
    )
    $desktop = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $desktop) { throw "Docker Desktopが見つかりません。" }
    Start-Process -FilePath $desktop | Out-Null
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        Start-Sleep -Seconds 1
        Add-DockerPath
        & docker info *> $null
        if ($LASTEXITCODE -eq 0) { return }
        Write-Progress -Activity "Docker Desktopを起動しています" -Status "$attempt / 120秒"
    }
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
    for ($attempt = 1; $attempt -le $Seconds; $attempt++) {
        try {
            $ready = Invoke-RestMethod -Uri "http://127.0.0.1:58000/ready" -TimeoutSec 3
            if ($ready.status -eq "ready") { return }
        } catch { }
        Start-Sleep -Seconds 1
        Write-Progress -Activity "予測基盤を準備しています" -Status "$attempt / $Seconds秒"
    }
    throw "予測基盤の準備が時間内に完了しませんでした。状態確認を実行してください。"
}

function Open-KibanUi {
    Start-Process "http://127.0.0.1:58000/ui/intake"
}

function Install-KibanShortcuts {
    $root = Get-KibanRoot
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $items = @(
        @{ Name = "予測基盤を起動"; Target = "予測基盤を起動.cmd" },
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
