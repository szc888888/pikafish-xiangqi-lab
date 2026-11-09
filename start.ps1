param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$apiDir = Join-Path $root 'apps\api'
$webDir = Join-Path $root 'apps\web'
$logsDir = Join-Path $root 'logs'
$apiLog = Join-Path $logsDir 'api-process.log'
$webLog = Join-Path $logsDir 'web-process.log'
$apiPython = Join-Path $apiDir '.venv\Scripts\python.exe'

if (-not (Test-Path $apiPython)) {
    $apiPython = (Get-Command python -ErrorAction Stop).Source
}
$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
if (-not $npm) {
    $npm = Get-Command npm -ErrorAction Stop
}

$apiCommand = "$apiPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1"
$webCommand = "$($npm.Source) run dev"

Write-Output "API directory: $apiDir"
Write-Output "API endpoint: http://127.0.0.1:8000"
Write-Output "API command: $apiCommand"
Write-Output "Web directory: $webDir"
Write-Output "Web endpoint: http://127.0.0.1:1239"
Write-Output "Web command: $webCommand"

if ($DryRun) {
    exit 0
}

function Write-LauncherEvent([string]$message) {
    Write-Output ("[launcher] " + $message)
}

function Test-HttpEndpoint([string]$url) {
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
    } catch {
        return $false
    }
}

function Wait-HttpEndpoint([string]$url, [int]$timeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    do {
        if (Test-HttpEndpoint $url) { return $true }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Show-StartupFailure([string]$service, [string]$logPath) {
    Write-LauncherEvent "startup failure: $service"
    Write-Output "Relevant process log: $logPath"
    if (Test-Path -LiteralPath $logPath) {
        Write-Output 'Recent process output (up to 40 lines):'
        Get-Content -LiteralPath $logPath -Tail 40
    } else {
        Write-Output 'No process log was written.'
    }
}

function Start-LoggedProcess(
    [string]$name,
    [string]$filePath,
    [string[]]$arguments,
    [string]$workingDirectory,
    [string]$logPath
) {
    # A hidden worker owns the service and drains both streams through a dedicated
    # PowerShell pipeline. It appends chunks and rotates between writes, so
    # rollover never interrupts the long-running API or Vite process.
    $workerShell = Get-Command pwsh -ErrorAction SilentlyContinue
    if (-not $workerShell) {
        $workerShell = Get-Command powershell -ErrorAction Stop
    }
    $config = @{
        Name = $name
        FilePath = $filePath
        Arguments = @($arguments)
        WorkingDirectory = $workingDirectory
        LogPath = $logPath
    } | ConvertTo-Json -Compress
    $configPayload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($config))
    $worker = @"
`$ErrorActionPreference = 'Stop'
`$config = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('$configPayload')) | ConvertFrom-Json
`$logPath = [string]`$config.LogPath
`$logLimit = 5 * 1024 * 1024
`$backupCount = 3
`$mutex = [Threading.Mutex]::new(`$false, ('Local\chess-process-log-' + [IO.Path]::GetFileNameWithoutExtension(`$logPath)))
`$utf8 = [Text.UTF8Encoding]::new(`$false)
function Rotate-ProcessLog() {
    if (-not (Test-Path -LiteralPath `$logPath)) { return }
    for (`$index = (`$backupCount - 1); `$index -ge 1; `$index--) {
        `$source = "`$logPath.`$index"
        `$destination = "`$logPath." + (`$index + 1)
        if (Test-Path -LiteralPath `$destination) { Remove-Item -LiteralPath `$destination -Force }
        if (Test-Path -LiteralPath `$source) { Move-Item -LiteralPath `$source -Destination `$destination -Force }
    }
    Move-Item -LiteralPath `$logPath -Destination ("`$logPath.1") -Force
}
function Write-ProcessLogBytes([byte[]]`$bytes) {
    if (`$bytes.Length -eq 0) { return }
    `$currentLength = if (Test-Path -LiteralPath `$logPath) { (Get-Item -LiteralPath `$logPath).Length } else { 0 }
    if ((`$currentLength + `$bytes.Length) -gt `$logLimit) { Rotate-ProcessLog }
    `$stream = [IO.File]::Open(`$logPath, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
    try { `$stream.Write(`$bytes, 0, `$bytes.Length) } finally { `$stream.Dispose() }
}
function Write-ProcessLogLine([string]`$line) {
    `$mutex.WaitOne()
    try {
        `$text = `$line + [Environment]::NewLine
        `$chunkStart = 0
        `$chunkBytes = 0
        for (`$index = 0; `$index -lt `$text.Length;) {
            `$unitLength = 1
            if ([char]::IsHighSurrogate(`$text[`$index]) -and (`$index + 1) -lt `$text.Length -and [char]::IsLowSurrogate(`$text[`$index + 1])) {
                `$unitLength = 2
            }
            `$unit = `$text.Substring(`$index, `$unitLength)
            `$unitBytes = `$utf8.GetByteCount(`$unit)
            if (`$chunkBytes -gt 0 -and (`$chunkBytes + `$unitBytes) -gt `$logLimit) {
                Write-ProcessLogBytes ([Text.Encoding]::UTF8.GetBytes(`$text.Substring(`$chunkStart, `$index - `$chunkStart)))
                `$chunkStart = `$index
                `$chunkBytes = 0
            }
            `$chunkBytes += `$unitBytes
            `$index += `$unitLength
        }
        if (`$chunkBytes -gt 0) {
            Write-ProcessLogBytes ([Text.Encoding]::UTF8.GetBytes(`$text.Substring(`$chunkStart)))
        }
    } finally {
        `$mutex.ReleaseMutex() | Out-Null
    }
}
Set-Location -LiteralPath ([string]`$config.WorkingDirectory)
`$arguments = @(`$config.Arguments)
Write-ProcessLogLine ("[launcher] process_started name={0} file={1}" -f [string]`$config.Name, [string]`$config.FilePath)
`$processExitCode = 0
try {
    # Native processes commonly write warnings to stderr; capture those lines
    # without letting PowerShell's Stop preference terminate the worker.
    `$previousErrorActionPreference = `$ErrorActionPreference
    `$ErrorActionPreference = 'Continue'
    & ([string]`$config.FilePath) @arguments 2>&1 | ForEach-Object {
        Write-ProcessLogLine ([string]`$_)
    }
    `$ErrorActionPreference = `$previousErrorActionPreference
    if (`$null -ne `$LASTEXITCODE) {
        `$processExitCode = [int]`$LASTEXITCODE
    }
} catch {
    Write-ProcessLogLine ("[launcher] process_error name={0} error={1}" -f [string]`$config.Name, [string]`$_.Exception.Message)
    `$processExitCode = 1
}
Write-ProcessLogLine ("[launcher] process_exited name={0} exit_code={1}" -f [string]`$config.Name, `$processExitCode)
exit `$processExitCode
"@
    $encodedWorker = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($worker))
    Start-Process -FilePath $workerShell.Source -ArgumentList @('-NoProfile', '-WindowStyle', 'Hidden', '-EncodedCommand', $encodedWorker) -WorkingDirectory $workingDirectory -WindowStyle Hidden | Out-Null
}

Write-LauncherEvent 'log preparation'
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
Write-LauncherEvent "process logs prepared: $apiLog and $webLog"

$apiHealthy = Test-HttpEndpoint 'http://127.0.0.1:8000/api/health'
if ($apiHealthy) {
    Write-LauncherEvent 'API reuse: health endpoint already available'
} else {
    Write-LauncherEvent "API start: output will append to $apiLog"
    try {
        Start-LoggedProcess 'API' $apiPython @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--workers', '1') $apiDir $apiLog
    } catch {
        Show-StartupFailure 'API' $apiLog
        throw
    }
}

if (-not (Wait-HttpEndpoint 'http://127.0.0.1:8000/api/health' 30)) {
    Show-StartupFailure 'API' $apiLog
    throw 'API service failed to start. See the API process log above.'
}
Write-LauncherEvent 'health-check success: API'

$webHealthy = Test-HttpEndpoint 'http://127.0.0.1:1239/'
if ($webHealthy) {
    Write-LauncherEvent 'web reuse: health endpoint already available'
} else {
    Write-LauncherEvent "web start: output will append to $webLog"
    try {
        Start-LoggedProcess 'web' $npm.Source @('run', 'dev') $webDir $webLog
    } catch {
        Show-StartupFailure 'web' $webLog
        throw
    }
}

if (-not (Wait-HttpEndpoint 'http://127.0.0.1:1239/' 30)) {
    Show-StartupFailure 'web' $webLog
    throw 'Web service failed to start. See the web process log above.'
}
Write-LauncherEvent 'health-check success: web'

Write-Output '服务已启动：'
Write-Output '  前端: http://127.0.0.1:1239/'
Write-Output '  API:  http://127.0.0.1:8000/'
Write-LauncherEvent 'launcher completion'
