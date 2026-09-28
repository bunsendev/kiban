Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "Kiban.Local.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Kiban.FieldPilot.psm1") -Force

function Get-RecoveryRoot($Install) {
    $root = [System.IO.Path]::GetFullPath((Join-Path $Install.DataRoot "Backup"))
    $data = [System.IO.Path]::GetFullPath($Install.DataRoot).TrimEnd("\") + "\"
    if (-not $root.StartsWith($data, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backupの保存先が不正です。"
    }
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    if ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Backupの保存先が不正です。"
    }
    return $root
}

function Assert-RecoveryChild([string]$Root, [string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($Root.TrimEnd("\") + "\",
        [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backup外のファイルは処理できません。"
    }
    return $full
}

function Get-RecoveryPolicy($Install) {
    $path = Join-Path $Install.DataRoot "Config\recovery-policy.json"
    if (Test-Path -LiteralPath $path) {
        $policy = Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json
    } else {
        $policy = [pscustomobject]@{
            daily_keep = 30; manual_keep = 30; pre_restore_keep = 5; pre_update_keep = 5
        }
    }
    foreach ($key in @("daily_keep", "manual_keep", "pre_restore_keep")) {
        $value = $policy.$key
        if ($null -eq $value -or [int]$value -lt 1 -or [int]$value -gt 365) {
            throw "Backup保持設定が不正です。"
        }
    }
    if ($null -eq $policy.PSObject.Properties["pre_update_keep"]) {
        $policy | Add-Member -NotePropertyName pre_update_keep -NotePropertyValue 5
    }
    if ([int]$policy.pre_update_keep -lt 1 -or [int]$policy.pre_update_keep -gt 365) {
        throw "Backup保持設定が不正です。"
    }
    return $policy
}

function Invoke-RecoveryPython($Install, [string[]]$Arguments) {
    $manifest = Join-Path $Install.AppRoot "SHA256SUMS.json"
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
        throw "アプリの配布照合情報がありません。"
    }
    $fingerprint = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()
    Invoke-FieldPilotCompose $Install (@(
        "run", "--rm", "--no-deps", "api", "python", "-m",
        "forecast_provider.field_pilot.recovery_bundle"
    ) + $Arguments + @("--release-fingerprint", $fingerprint)) | Out-Null
}

function New-FieldPilotBackup($Install, [ValidateSet("daily", "manual", "pre-restore", "pre-update")]
    [string]$Trigger = "manual", [switch]$SettingsOnly) {
    $root = Get-RecoveryRoot $Install
    $policy = Get-RecoveryPolicy $Install
    $identity = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") + "-" +
        [guid]::NewGuid().ToString("N")
    $archiveName = if ($SettingsOnly) { "settings-export-$identity.zip" } else {
        "recovery-$Trigger-$identity.zip"
    }
    $archive = Assert-RecoveryChild $root (Join-Path $root $archiveName)
    $dumpName = ".postgres-$identity.dump"
    $dump = Assert-RecoveryChild $root (Join-Path $root $dumpName)
    $stopped = $false
    try {
        Invoke-FieldPilotCompose $Install @("stop", "api") | Out-Null
        $stopped = $true
        Invoke-FieldPilotCompose $Install @("up", "-d", "postgres") | Out-Null
        $arguments = @(
            "create", "--data-root", "/var/lib/kiban", "--output",
            "/var/lib/kiban/pilot-backup/$archiveName", "--mode",
            $(if ($SettingsOnly) { "SETTINGS" } else { "FULL" }),
            "--config-dir", "/var/lib/kiban/pilot",
            "--settings-dir", "/var/lib/kiban/pilot-settings",
            "--inbox-dir", "/var/lib/kiban/pilot-inbox"
        )
        if (-not $SettingsOnly) {
            Invoke-FieldPilotCompose $Install @(
                "exec", "-T", "postgres", "pg_dump", "-U", "kiban", "-d", "kiban",
                "-Fc", "--file", "/var/lib/kiban/pilot-backup/$dumpName"
            ) | Out-Null
            Invoke-FieldPilotCompose $Install @(
                "exec", "-T", "postgres", "chmod", "0644",
                "/var/lib/kiban/pilot-backup/$dumpName"
            ) | Out-Null
            $arguments += @("--postgres-dump", "/var/lib/kiban/pilot-backup/$dumpName")
        }
        Invoke-RecoveryPython $Install $arguments
        Invoke-RecoveryPython $Install @(
            "verify", "--bundle", "/var/lib/kiban/pilot-backup/$archiveName"
        )
        if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
            throw "Backupを確認できません。"
        }
        Write-FieldPilotLog $Install.DataRoot "backup_$Trigger" "completed"
    } catch {
        Write-FieldPilotLog $Install.DataRoot "backup_$Trigger" "failed"
        throw
    } finally {
        if (Test-Path -LiteralPath $dump) { Remove-Item -LiteralPath $dump -Force }
        if ($stopped) {
            Invoke-FieldPilotCompose $Install @("up", "-d", "api") | Out-Null
            Wait-FieldPilotReady $Install
        }
    }
    if (-not $SettingsOnly) {
        $key = $Trigger.Replace("-", "_") + "_keep"
        $keep = [int]$policy.$key
        $old = @(Get-ChildItem -LiteralPath $root -Filter "recovery-$Trigger-*.zip" -File |
            Sort-Object -Property Name -Descending | Select-Object -Skip $keep)
        foreach ($file in $old) {
            $target = Assert-RecoveryChild $root $file.FullName
            if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Backupファイルが不正です。"
            }
            Remove-Item -LiteralPath $target -Force
        }
    }
    return $archive
}

function Stage-FieldPilotBackup($Install, [string]$ArchivePath, [string]$StageName) {
    $root = Get-RecoveryRoot $Install
    $archive = Assert-RecoveryChild $root $ArchivePath
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf) -or
        ((Get-Item -LiteralPath $archive).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "復元ファイルを確認できません。"
    }
    $stage = Assert-RecoveryChild $root (Join-Path $root $StageName)
    Invoke-RecoveryPython $Install @(
        "stage", "--bundle", "/var/lib/kiban/pilot-backup/$([IO.Path]::GetFileName($archive))",
        "--destination", "/var/lib/kiban/pilot-backup/$StageName"
    )
    $manifest = Get-Content -LiteralPath (Join-Path $stage "manifest.json") `
        -Raw -Encoding utf8 | ConvertFrom-Json
    if ($manifest.mode -eq "FULL") {
        Invoke-FieldPilotCompose $Install @(
            "run", "--rm", "--no-deps", "postgres", "pg_restore", "--list",
            "/var/lib/kiban/pilot-backup/$StageName/database/postgres.dump"
        ) | Out-Null
    }
    return $stage
}

function Copy-RecoveryFile([string]$Source, [string]$Target) {
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { return }
    $parent = [IO.Path]::GetDirectoryName($Target)
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Target.recovery-$([guid]::NewGuid().ToString('N')).tmp"
    try {
        Copy-Item -LiteralPath $Source -Destination $temporary
        if (Test-Path -LiteralPath $Target -PathType Leaf) {
            [IO.File]::Replace($temporary, $Target, $null)
        } else {
            [IO.File]::Move($temporary, $Target)
        }
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Apply-FieldPilotFiles($Install, [string]$Stage, [switch]$Exact) {
    $data = $Install.DataRoot
    $files = @{
        "config/pilot-settings.json" = "Config/pilot-settings.json"
        "config/inbox-policy.json" = "Config/inbox-policy.json"
        "config/recovery-policy.json" = "Config/recovery-policy.json"
        "config/feedback-client.json" = "Config/feedback-client.json"
        "config/feedback-server-public.pem" = "Config/feedback-server-public.pem"
        "config/feedback-update-public.pem" = "Config/feedback-update-public.pem"
        "config/release-update-public.pem" = "Config/release-update-public.pem"
        "settings/field-settings.sqlite3" = "LocalSettings/field-settings.sqlite3"
        "settings/update-checks.sqlite3" = "LocalSettings/update-checks.sqlite3"
        "learning/inbox.sqlite3" = "Inbox/inbox.sqlite3"
        "learning/improvement-events.sqlite3" = "Inbox/improvement-events.sqlite3"
        "learning/feedback.sqlite3" = "Inbox/feedback.sqlite3"
    }
    foreach ($entry in $files.GetEnumerator()) {
        $source = Join-Path $Stage $entry.Key
        $target = Join-Path $data $entry.Value
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-RecoveryFile $source $target
        } elseif ($Exact -and (Test-Path -LiteralPath $target -PathType Leaf)) {
            Remove-Item -LiteralPath $target -Force
        }
    }
}

function Invoke-FieldPilotDatabaseRestore($Install, [string]$Stage) {
    $name = Split-Path -Leaf $Stage
    $dump = Join-Path $Stage "database\postgres.dump"
    if (-not (Test-Path -LiteralPath $dump -PathType Leaf)) {
        throw "PostgreSQLの復元データがありません。"
    }
    Invoke-FieldPilotCompose $Install @(
        "exec", "-T", "postgres", "pg_restore", "-U", "kiban", "-d", "kiban",
        "--clean", "--if-exists", "--no-owner", "--no-privileges", "--exit-on-error",
        "/var/lib/kiban/pilot-backup/$name/database/postgres.dump"
    ) | Out-Null
}

function Restore-FieldPilotBackup($Install, [string]$BundlePath) {
    $root = Get-RecoveryRoot $Install
    if (-not (Test-Path -LiteralPath $BundlePath -PathType Leaf) -or
        ((Get-Item -LiteralPath $BundlePath).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "復元元ZIPを確認できません。"
    }
    $incomingName = "incoming-$([guid]::NewGuid().ToString('N')).zip"
    $incoming = Assert-RecoveryChild $root (Join-Path $root $incomingName)
    Copy-Item -LiteralPath $BundlePath -Destination $incoming
    $stageName = "restore-stage-$([guid]::NewGuid().ToString('N'))"
    $stage = $null
    $before = $null
    $beforeStage = $null
    $applied = $false
    try {
        $stage = Stage-FieldPilotBackup $Install $incoming $stageName
        $manifest = Get-Content -LiteralPath (Join-Path $stage "manifest.json") `
            -Raw -Encoding utf8 | ConvertFrom-Json
        $before = New-FieldPilotBackup $Install -Trigger "pre-restore"
        $beforeStage = Stage-FieldPilotBackup $Install $before `
            "rollback-stage-$([guid]::NewGuid().ToString('N'))"
        Invoke-FieldPilotCompose $Install @("stop", "api") | Out-Null
        $applied = $true
        if ($manifest.mode -eq "FULL") { Invoke-FieldPilotDatabaseRestore $Install $stage }
        Apply-FieldPilotFiles $Install $stage -Exact
        Invoke-FieldPilotCompose $Install @("up", "-d", "api") | Out-Null
        Wait-FieldPilotReady $Install
        Write-FieldPilotLog $Install.DataRoot "restore" "completed"
    } catch {
        if ($applied -and $beforeStage) {
            try {
                Invoke-FieldPilotCompose $Install @("stop", "api") | Out-Null
                if ($manifest.mode -eq "FULL") {
                    Invoke-FieldPilotDatabaseRestore $Install $beforeStage
                }
                Apply-FieldPilotFiles $Install $beforeStage -Exact
                Invoke-FieldPilotCompose $Install @("up", "-d", "api") | Out-Null
                Wait-FieldPilotReady $Install
                Write-FieldPilotLog $Install.DataRoot "restore" "rolled_back"
            } catch {
                Write-FieldPilotLog $Install.DataRoot "restore" "rollback_failed"
                throw "復元に失敗し、元の状態への復帰も失敗しました。管理担当者へ連絡してください。"
            }
        }
        Write-FieldPilotLog $Install.DataRoot "restore" "failed"
        throw
    } finally {
        if (Test-Path -LiteralPath $incoming) { Remove-Item -LiteralPath $incoming -Force }
        foreach ($directory in @($stage, $beforeStage)) {
            if ($directory -and (Test-Path -LiteralPath $directory -PathType Container)) {
                $checked = Assert-RecoveryChild $root $directory
                if ((Get-Item -LiteralPath $checked).Attributes -band
                    [IO.FileAttributes]::ReparsePoint) {
                    throw "復元作業フォルダが不正です。"
                }
                Remove-Item -LiteralPath $checked -Recurse -Force
            }
        }
    }
}

Export-ModuleMember -Function New-FieldPilotBackup, Restore-FieldPilotBackup
