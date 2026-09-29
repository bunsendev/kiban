if ($env:BUNSEN_INSTALL_ENTRY_MARKER) {
    try {
        [IO.File]::WriteAllText($env:BUNSEN_INSTALL_ENTRY_MARKER, 'INSTALL_SCRIPT_ENTERED')
    } catch { }
}
$ErrorActionPreference = 'Stop'
$diagnosticDir = Join-Path $env:LOCALAPPDATA 'Bunsen\FieldPilot\InstallerLogs'
New-Item -ItemType Directory -Path $diagnosticDir -Force | Out-Null
$diagnosticFile = Join-Path $diagnosticDir 'setup-last-error.txt'
$progressFile = Join-Path $diagnosticDir 'setup-progress-last.txt'
$transcriptFile = Join-Path $diagnosticDir 'setup-transcript-last.txt'
$childOutputFile = Join-Path $diagnosticDir 'field-pilot-setup-output-last.txt'
$completionFile = Join-Path $diagnosticDir 'setup-complete-last.txt'
$step = 'startup'
$setupCode = 1
$transcriptStarted = $false

function Set-SetupStep([string]$name) {
    $script:step = $name
    Add-Content -LiteralPath $progressFile -Value "$(Get-Date -Format o) | $name" -Encoding utf8
}

Set-Content -LiteralPath $progressFile -Value "$(Get-Date -Format o) | setup started" -Encoding utf8
try {
    Start-Transcript -LiteralPath $transcriptFile -Force | Out-Null
    $transcriptStarted = $true
    Set-SetupStep 'ZIP verification'
    $zip = Join-Path $PSScriptRoot 'payload.zip'
    $expected = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'sha256.txt') -Raw).Trim()
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'Installer payload integrity check failed.'
    }
    Set-SetupStep 'ZIP extraction'
    $root = Join-Path $env:TEMP ('BunsenFieldPilot-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    try {
        Expand-Archive -LiteralPath $zip -DestinationPath $root -Force
        $setup = Join-Path $root 'appendix_d\installer\windows\field-pilot-setup.ps1'
        if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) { throw 'Setup missing.' }
        Set-SetupStep 'Update public key'
        $key = Join-Path $PSScriptRoot 'update-public.pem'
        if (Test-Path -LiteralPath $key) {
            $targetKey = Join-Path $env:LOCALAPPDATA 'Bunsen\FieldPilot\Data\Config\release-update-public.pem'
            if (Test-Path -LiteralPath $targetKey) {
                if ((Get-FileHash $key -Algorithm SHA256).Hash -ne
                    (Get-FileHash $targetKey -Algorithm SHA256).Hash) {
                    throw 'Update trust root differs from installed key.'
                }
            } else {
                New-Item -ItemType Directory -Path (Split-Path $targetKey -Parent) -Force | Out-Null
                Copy-Item -LiteralPath $key -Destination $targetKey
            }
        }
        Set-SetupStep 'Field Pilot setup'
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) {
            throw 'Windows PowerShell was not found.'
        }
        Set-Content -LiteralPath $childOutputFile -Value 'Field Pilot setup output:' -Encoding utf8
        $previousModulePath = $env:PSModulePath
        try {
            $env:PSModulePath = ''
            & $powershell -NoProfile -ExecutionPolicy Bypass -File $setup 2>&1 |
                ForEach-Object {
                    $line = [string]$_
                    Add-Content -LiteralPath $childOutputFile -Value $line -Encoding utf8
                    Write-Host $line
                }
            $setupCode = $LASTEXITCODE
        } finally {
            $env:PSModulePath = $previousModulePath
        }
        Add-Content -LiteralPath $childOutputFile -Value "Exit code: $setupCode" -Encoding utf8
        Set-SetupStep "Field Pilot setup returned: $setupCode"
        if ($setupCode -ne 0) { throw "Field Pilot setup exited: $setupCode" }
    } finally {
        $safeRoot = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
        $safeTarget = [System.IO.Path]::GetFullPath($root)
        if ($safeTarget.StartsWith($safeRoot, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $root -Recurse -Force
        }
    }
    Remove-Item -LiteralPath $diagnosticFile -ErrorAction SilentlyContinue
    Set-SetupStep 'completed'
    Set-Content -LiteralPath $completionFile -Value "Completed: $((Get-Date).ToString('o'))" -Encoding utf8
} catch {
    $setupCode = 1
    $message = $_.Exception.Message
    @("Time: $((Get-Date).ToString('o'))", "Step: $step", "Error: $message",
        "Exception: $($_.Exception.GetType().FullName)",
        "Location: $($_.InvocationInfo.PositionMessage)") |
        Set-Content -LiteralPath $diagnosticFile -Encoding utf8
    Set-SetupStep "failed: $step"
    Write-Host "インストールを完了できませんでした。処理: $step" -ForegroundColor Red
    Write-Host "原因: $message" -ForegroundColor Red
    Write-Host "診断ログ: $diagnosticDir"
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
exit $setupCode
