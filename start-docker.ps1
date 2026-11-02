$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$docker = Get-Command docker -ErrorAction Stop
& $docker.Source compose version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Compose v2 is required. Start Docker Desktop and try again.'
}

$dockerPlatform = & $docker.Source info --format '{{.OSType}}/{{.Architecture}}'
if ($LASTEXITCODE -ne 0 -or $dockerPlatform -notmatch '^linux/(x86_64|amd64)$') {
    throw "Docker must use Linux containers on x86-64 to run the official Pikafish build. Detected: $dockerPlatform"
}

$engineDirectory = Join-Path $root 'engine\linux-x86-64'
$enginePath = Join-Path $engineDirectory 'pikafish'
$networkPath = Join-Path $engineDirectory 'pikafish.nnue'
if (-not (Test-Path -LiteralPath $enginePath) -or -not (Test-Path -LiteralPath $networkPath)) {
    Write-Output 'Installing the official Linux x86-64 Pikafish engine for Docker...'
    & (Join-Path $root 'scripts\install-engine.ps1') -Platform Linux -InstallDirectory $engineDirectory -Force
    if ($LASTEXITCODE -ne 0) {
        throw 'Pikafish installation failed. See the installer output above.'
    }
}

& $docker.Source compose up --build -d
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Compose failed to start. Check the output above.'
}

Write-Output 'Docker services are starting:'
Write-Output '  Web: http://127.0.0.1:1240/'
Write-Output '  API: http://127.0.0.1:8010/api/health'
Write-Output 'Stop them with: docker compose down'
