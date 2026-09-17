Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force

function Get-KibanStandardAnalysisServices {
    return @(
        "postgres", "api",
        "mapping-dry-run-worker", "inventory-normalization-worker",
        "import-worker", "normalization-worker", "matching-worker",
        "daily-worker", "selection-worker", "acceptance-worker",
        "worker", "provider-conformance-worker", "comparison-campaign-worker",
        "statsforecast-worker", "statsforecast-conformance-worker",
        "mlforecast-worker", "mlforecast-conformance-worker"
    )
}

function Get-KibanManagedServices {
    return @(
        (Get-KibanStandardAnalysisServices)
        "worker-storage-init"
        "timesfm-worker"
        "timesfm-conformance-worker"
    ) | Select-Object -Unique
}

function Get-KibanComputerCapacity {
    $computer = Get-CimInstance Win32_ComputerSystem
    $operatingSystem = Get-CimInstance Win32_OperatingSystem
    $drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot((Get-KibanRoot)).TrimEnd(":\"))
    return [pscustomobject]@{
        LogicalProcessors = [int]$computer.NumberOfLogicalProcessors
        TotalMemoryGB = [math]::Round($computer.TotalPhysicalMemory / 1GB, 1)
        FreeMemoryGB = [math]::Round($operatingSystem.FreePhysicalMemory * 1KB / 1GB, 1)
        FreeDiskGB = [math]::Round($drive.Free / 1GB, 1)
    }
}

function Assert-KibanAnalysisCapacity([switch]$IncludeTimesFm) {
    $capacity = Get-KibanComputerCapacity
    Write-Host ("PC資源: CPU {0} threads / RAM {1} GB（空き {2} GB）/ disk空き {3} GB" -f `
        $capacity.LogicalProcessors, $capacity.TotalMemoryGB, $capacity.FreeMemoryGB, $capacity.FreeDiskGB)
    if ($capacity.LogicalProcessors -lt 4) { throw "予測分析にはCPU 4 thread以上が必要です。" }
    if ($IncludeTimesFm -and ($capacity.TotalMemoryGB -lt 15 -or $capacity.FreeMemoryGB -lt 6)) {
        throw "TimesFM追加にはRAM 15 GB以上、現在の空き6 GB以上が必要です。アプリを閉じて再実行してください。"
    }
    if (-not $IncludeTimesFm -and ($capacity.TotalMemoryGB -lt 8 -or $capacity.FreeMemoryGB -lt 3)) {
        throw "標準OSS分析にはRAM 8 GB以上、現在の空き3 GB以上が必要です。アプリを閉じて再実行してください。"
    }
    if ($capacity.FreeDiskGB -lt 15) {
        throw "予測分析には15 GB以上のディスク空き容量が必要です。"
    }
    return $capacity
}

function Get-KibanLocalToken {
    $environmentPath = Join-Path (Get-KibanRoot) ".env"
    if (-not (Test-Path -LiteralPath $environmentPath -PathType Leaf)) {
        throw ".envがありません。現場PCセットアップを先に実行してください。"
    }
    $tokenLine = Get-Content -LiteralPath $environmentPath |
        Where-Object { $_ -like "KIBAN_API_TOKEN=*" } |
        Select-Object -First 1
    if (-not $tokenLine) { throw ".envに接続コードがありません。" }
    return $tokenLine.Substring("KIBAN_API_TOKEN=".Length)
}

function Get-KibanRunningServices {
    $root = Get-KibanRoot
    Push-Location $root
    try {
        $values = @(& docker compose ps --services --status running 2>$null)
        if ($LASTEXITCODE -ne 0) { throw "Docker service状態を確認できませんでした。" }
        return $values
    } finally { Pop-Location }
}

function Start-KibanAnalysisServices([switch]$IncludeTimesFm) {
    $arguments = @(
        "--profile", "worker",
        "--profile", "statsforecast-worker",
        "--profile", "mlforecast-worker"
    )
    if ($IncludeTimesFm) { $arguments += @("--profile", "timesfm-worker") }
    $arguments += @("up", "-d", "--build")
    $arguments += Get-KibanStandardAnalysisServices
    if ($IncludeTimesFm) {
        $arguments += @("timesfm-worker", "timesfm-conformance-worker")
    }
    Invoke-KibanCompose $arguments
}

function Wait-KibanAnalysisReady([switch]$IncludeTimesFm, [int]$Seconds = 240) {
    $expectedServices = @(Get-KibanStandardAnalysisServices)
    $expectedProviders = @("builtin-baseline", "statsforecast-ets", "mlforecast-ridge")
    if ($IncludeTimesFm) {
        $expectedServices += @("timesfm-worker", "timesfm-conformance-worker")
        $expectedProviders += "timesfm-2p5"
    }
    $token = Get-KibanLocalToken
    $headers = @{ Authorization = "Bearer $token" }
    $baseUri = Get-KibanBaseUri
    for ($attempt = 1; $attempt -le $Seconds; $attempt++) {
        try {
            $ready = Invoke-RestMethod -Uri "$baseUri/ready" -TimeoutSec 3
            $running = @(Get-KibanRunningServices)
            $missingServices = @($expectedServices | Where-Object { $_ -notin $running })
            $workers = @(Invoke-RestMethod -Uri "$baseUri/api/worker-status" `
                -Headers $headers -TimeoutSec 3)
            $onlineProviders = @($workers | ForEach-Object { $_ } |
                Where-Object { $_.status -in @("ONLINE", "WORKING") } |
                ForEach-Object { $_.provider_id })
            $missingProviders = @($expectedProviders | Where-Object { $_ -notin $onlineProviders })
            if ($ready.status -eq "ready" -and -not $missingServices -and -not $missingProviders) {
                return
            }
        } catch { }
        Start-Sleep -Seconds 1
        Write-Progress -Activity "予測OSS分析を準備しています" -Status "$attempt / ${Seconds}秒"
    }
    throw "予測OSS分析のWorkerを時間内に準備できませんでした。状態確認を実行してください。"
}

function Get-KibanAnalysisStatus {
    $running = @(Get-KibanRunningServices)
    $standard = @(Get-KibanStandardAnalysisServices)
    $missing = @($standard | Where-Object { $_ -notin $running })
    $timesFm = @("timesfm-worker", "timesfm-conformance-worker")
    return [pscustomobject]@{
        StandardReady = $missing.Count -eq 0
        MissingServices = $missing
        TimesFmReady = @($timesFm | Where-Object { $_ -notin $running }).Count -eq 0
    }
}

function Open-KibanAnalysisUi {
    Start-Process "$(Get-KibanBaseUri)/ui/analysis"
}

Export-ModuleMember -Function *
