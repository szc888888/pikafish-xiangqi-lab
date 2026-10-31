param(
    [string]$OutputDirectory = $env:BACKUP_OUTPUT_DIR,
    [int]$RetentionDays = 30,
    [switch]$WhatIf
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'pg-common.ps1')
if ($RetentionDays -lt 30) { throw 'Backup retention must be at least 30 days' }
$uri = Get-ChessDatabaseUri
if ($WhatIf) {
    $displayDirectory = if ($OutputDirectory) { $OutputDirectory } else { '<BACKUP_OUTPUT_DIR>' }
    Write-Output "Would create an encrypted PostgreSQL custom-format backup of $($uri.Host)/$($uri.AbsolutePath.TrimStart('/')) in $displayDirectory"
    Write-Output "Would retain encrypted backups for $RetentionDays days and require the external deletion ledger during restore"
    exit 0
}
if (-not $OutputDirectory) { throw 'BACKUP_OUTPUT_DIR is required for an operational backup' }
if (-not $env:DELETION_LEDGER_PATH) { throw 'DELETION_LEDGER_PATH is required for an operational backup' }
if (-not $env:BACKUP_ENCRYPTION_KEY) { throw 'BACKUP_ENCRYPTION_KEY is required (base64-encoded 32 bytes)' }
$destination = [IO.Path]::GetFullPath($OutputDirectory)
$ledger = [IO.Path]::GetFullPath($env:DELETION_LEDGER_PATH)
$env:DELETION_LEDGER_PATH = $ledger
if ($ledger.StartsWith($destination.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Deletion ledger must be stored separately from backup archives'
}
$dumpTool = Find-PgTool 'pg_dump'
$restoreTool = Find-PgTool 'pg_restore'
$python = Find-ChessPython
$apiDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'apps\api'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $ledger) -Force | Out-Null
if (-not (Test-Path -LiteralPath $ledger)) { New-Item -ItemType File -Path $ledger -ErrorAction Stop | Out-Null }
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$plain = Join-Path $destination "chess-$stamp.dump"
$encrypted = "$plain.enc"
try {
    Set-PgConnectionEnvironment $uri
    Push-Location $apiDir
    try { & $python -m app.deletion_ledger purge } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'Expired account purge failed; backup aborted' }
    & $dumpTool -Fc --no-owner --no-privileges -f $plain
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }
    & $restoreTool --list $plain | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'pg_restore could not read the dump' }
    Push-Location $apiDir
    try { & $python -m app.backup_crypto encrypt $plain $encrypted } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $encrypted)) { throw 'Backup encryption failed' }
    Get-ChildItem -LiteralPath $destination -Filter 'chess-*.dump.enc' -File | Where-Object { $_.LastWriteTimeUtc -lt [DateTime]::UtcNow.AddDays(-$RetentionDays) } | Remove-Item -Force
    Write-Output "Backup created: $encrypted"
} finally {
    Remove-Item -LiteralPath $plain -Force -ErrorAction SilentlyContinue
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
