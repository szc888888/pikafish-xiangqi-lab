param([string]$TaskName = 'ChessDailyBackup', [switch]$WhatIf)
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'backup-chess.ps1'
if ($WhatIf) { Write-Output "Would register $TaskName to run $script daily at 02:00"; exit 0 }
foreach ($name in @('BACKUP_ENCRYPTION_KEY', 'BACKUP_OUTPUT_DIR', 'DELETION_LEDGER_PATH')) {
    if (-not [Environment]::GetEnvironmentVariable($name, 'User') -and -not [Environment]::GetEnvironmentVariable($name, 'Machine')) {
        throw "Set $name persistently for the scheduled task account first"
    }
}
$shell = (Get-Command pwsh -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute $shell -Argument "-NoProfile -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At '02:00'
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Description 'Daily encrypted chess PostgreSQL backup' -Force | Out-Null
Write-Output "Registered backup task: $TaskName"
