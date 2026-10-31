Set-StrictMode -Version Latest

function Get-ChessDatabaseUri {
    $value = $env:DATABASE_URL
    if (-not $value) {
        $root = Split-Path -Parent $PSScriptRoot
        $entry = Get-Content -LiteralPath (Join-Path $root '.env') | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
        if ($entry) { $value = $entry.Substring('DATABASE_URL='.Length).Trim() }
    }
    if (-not $value -or $value -notmatch '^postgresql(\+psycopg)?://') { throw 'DATABASE_URL must point to PostgreSQL' }
    return [Uri]($value -replace '^postgresql\+psycopg://', 'postgresql://')
}

function Set-PgConnectionEnvironment([Uri]$uri) {
    $parts = $uri.UserInfo.Split(':', 2)
    if ($parts.Count -ne 2) { throw 'DATABASE_URL must contain user and password' }
    $env:PGHOST = $uri.Host
    $env:PGPORT = [string]$uri.Port
    $env:PGUSER = [Uri]::UnescapeDataString($parts[0])
    $env:PGPASSWORD = [Uri]::UnescapeDataString($parts[1])
    $env:PGDATABASE = $uri.AbsolutePath.TrimStart('/')
}

function Find-PgTool([string]$name) {
    if ($env:PG_BIN_DIR) {
        $path = Join-Path $env:PG_BIN_DIR "$name.exe"
        if (Test-Path -LiteralPath $path) { return $path }
    }
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "$name not found; install PostgreSQL client tools or set PG_BIN_DIR"
}

function Find-ChessPython {
    $root = Split-Path -Parent $PSScriptRoot
    $venv = Join-Path $root 'apps\api\.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venv) { return $venv }
    return (Get-Command python -ErrorAction Stop).Source
}
