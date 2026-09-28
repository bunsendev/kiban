param([Parameter(Mandatory = $true)][string]$DataRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$inbox = Join-Path $DataRoot "Inbox"
$drop = Join-Path $inbox "Drop"
$staged = Join-Path $inbox "Staged"
$observed = Join-Path $inbox "Observed"
$policyPath = Join-Path $DataRoot "Config\inbox-policy.json"
$policyFingerprint = if (Test-Path -LiteralPath $policyPath -PathType Leaf) {
    (Get-FileHash -LiteralPath $policyPath -Algorithm SHA256).Hash.ToLowerInvariant()
} else { "UNCONFIGURED" }
foreach ($directory in @($drop, $staged, $observed)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    if ((Get-Item -LiteralPath $directory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "投入先の設定が不正です。"
    }
}

$sha = [Security.Cryptography.SHA256]::Create()
try {
    foreach ($file in @(Get-ChildItem -LiteralPath $drop -File -Force)) {
        if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        if ($file.Length -le 0 -or $file.Length -gt 2000000000) { continue }
        if ([IO.Path]::GetExtension($file.Name).ToLowerInvariant() -notin @(".csv", ".pdf")) { continue }
        # コピー中のファイルを採用しない。時刻とサイズが安定し、排他オープンできる時だけ読む。
        $firstLength = $file.Length
        $firstTicks = $file.LastWriteTimeUtc.Ticks
        Start-Sleep -Seconds 2
        $second = Get-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
        if ($null -eq $second -or $second.Length -ne $firstLength -or
            $second.LastWriteTimeUtc.Ticks -ne $firstTicks) { continue }
        $identity = "{0}`n{1}`n{2}`n{3}" -f $file.Name, $firstLength, $firstTicks, $policyFingerprint
        $keyBytes = [Text.Encoding]::UTF8.GetBytes($identity)
        $key = ([BitConverter]::ToString($sha.ComputeHash($keyBytes))).Replace("-", "").ToLowerInvariant()
        $marker = Join-Path $observed ($key + ".done")
        $source = $null
        $temporary = $null
        try {
            $source = [IO.FileStream]::new($file.FullName, [IO.FileMode]::Open,
                [IO.FileAccess]::Read, [IO.FileShare]::None)
            if ($source.Length -ne $firstLength -or
                (Get-Item -LiteralPath $file.FullName).LastWriteTimeUtc.Ticks -ne $firstTicks) {
                continue
            }
            $digest = ([BitConverter]::ToString($sha.ComputeHash($source))).Replace("-", "").ToLowerInvariant()
            $source.Position = 0
            if ((Test-Path -LiteralPath $marker -PathType Leaf) -and
                (Get-Content -LiteralPath $marker -Raw -Encoding utf8).Trim() -eq $digest) {
                continue
            }
            $stageId = [guid]::NewGuid().ToString("N")
            $temporary = Join-Path $staged ($stageId + ".tmp")
            $binary = Join-Path $staged ($stageId + ".bin")
            $metadata = Join-Path $staged ($stageId + ".json")
            $writer = [IO.FileStream]::new($temporary, [IO.FileMode]::CreateNew,
                [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                $source.CopyTo($writer)
                $writer.Flush($true)
            } finally { $writer.Dispose() }
            $source.Dispose()
            $source = $null
            if ((Get-Item -LiteralPath $temporary).Length -ne $firstLength) { continue }
            [IO.File]::Move($temporary, $binary)
            $temporary = $null
            $manifest = [pscustomobject]@{
                original_name = $file.Name
                sha256 = $digest
                size_bytes = $firstLength
                received_at = (Get-Date).ToUniversalTime().ToString("o")
            } | ConvertTo-Json -Compress
            $manifestTemporary = Join-Path $staged ($stageId + ".json.tmp")
            [IO.File]::WriteAllText($manifestTemporary, $manifest, [Text.UTF8Encoding]::new($false))
            [IO.File]::Move($manifestTemporary, $metadata)
            [IO.File]::WriteAllText($marker, $digest, [Text.UTF8Encoding]::new($false))
        } catch [IO.IOException] {
            # 他のアプリが書き込み中なら次回起動で再確認する。
            continue
        } finally {
            if ($null -ne $source) { $source.Dispose() }
            if ($null -ne $temporary -and [IO.File]::Exists($temporary)) {
                [IO.File]::Delete($temporary)
            }
        }
    }
} finally { $sha.Dispose() }
