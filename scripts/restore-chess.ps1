param(
    [Parameter(Mandatory)][string]$Archive,
    [Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9_]{0,62}$')][string]$TargetDatabase,
    [Parameter(Mandatory)][string]$LedgerPath,
    [switch]$ConfirmRestore,
    [switch]$WhatIf
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'pg-common.ps1')
$uri = Get-ChessDatabaseUri
if ($TargetDatabase -eq $uri.AbsolutePath.TrimStart('/')) { throw 'Restore target must differ from the live database' }
if ($WhatIf) {
    Write-Output "Would decrypt $Archive, create isolated database $TargetDatabase, restore, then replay $LedgerPath"
    exit 0
}
if (-not $ConfirmRestore) { throw 'Pass -ConfirmRestore after reviewing the target database and ledger' }
if (-not (Test-Path -LiteralPath $Archive) -or -not (Test-Path -LiteralPath $LedgerPath)) { throw 'Archive and latest deletion ledger must exist' }
if (-not $env:BACKUP_ENCRYPTION_KEY) { throw 'BACKUP_ENCRYPTION_KEY is required' }
$createdb = Find-PgTool 'createdb'
$psql = Find-PgTool 'psql'
$restoreTool = Find-PgTool 'pg_restore'
$python = Find-ChessPython
$apiDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'apps\api'
$plain = Join-Path ([IO.Path]::GetTempPath()) ("chess-restore-" + [Guid]::NewGuid().ToString('N') + '.dump')
try {
    Set-PgConnectionEnvironment $uri
    $exists = & $psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$TargetDatabase'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect target database' }
    if ($exists -match '1') { throw 'Target database already exists' }
    Push-Location $apiDir
    try { & $python -m app.backup_crypto decrypt $Archive $plain } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'Backup decryption failed' }
    & $createdb $TargetDatabase
    if ($LASTEXITCODE -ne 0) { throw 'Could not create target database' }
    & $restoreTool --no-owner --no-privileges --exit-on-error -d $TargetDatabase $plain
    if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed; isolated target needs inspection' }
    $builder = [UriBuilder]::new($uri)
    $builder.Path = "/$TargetDatabase"
    $env:DATABASE_URL = ($builder.Uri.AbsoluteUri -replace '^postgresql://', 'postgresql+psycopg://')
    Push-Location $apiDir
    try { & $python -m app.deletion_ledger replay --ledger $LedgerPath } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'Deletion ledger replay failed; do not serve restored database' }
    Push-Location $apiDir
    try { & $python -c 'from app.database import assert_database_migrated; assert_database_migrated()' } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'Restored database migration revision does not match application head' }
    & $psql -d $TargetDatabase -tAc 'SELECT version_num FROM alembic_version'
    if ($LASTEXITCODE -ne 0) { throw 'Migration verification failed' }
    Write-Output "Restore drill complete in isolated database $TargetDatabase"
} finally {
    Remove-Item -LiteralPath $plain -Force -ErrorAction SilentlyContinue
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
