[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Version = 'latest',
    [string]$InstallDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) 'engine'),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repository = 'official-pikafish/Pikafish'
$headers = @{
    Accept = 'application/vnd.github+json'
    'User-Agent' = 'Pikafish-Xiangqi-Lab-engine-installer'
}

if ($Version -eq 'latest') {
    $releaseUri = "https://api.github.com/repos/$repository/releases/latest"
} else {
    $escapedVersion = [Uri]::EscapeDataString($Version)
    $releaseUri = "https://api.github.com/repos/$repository/releases/tags/$escapedVersion"
}

try {
    $release = Invoke-RestMethod -Uri $releaseUri -Headers $headers -TimeoutSec 30
} catch {
    throw "无法读取 Pikafish 官方发布信息。请检查网络连接，或稍后重试。详情：$($_.Exception.Message)"
}

$archiveAssets = @($release.assets | Where-Object { $_.name -match '^Pikafish\..+\.7z$' })
if ($archiveAssets.Count -ne 1) {
    throw "发布 $($release.tag_name) 中没有唯一的 Pikafish .7z 发布包，已停止安装以避免选错文件。"
}

$targetDirectory = [IO.Path]::GetFullPath($InstallDirectory)
$engineTarget = Join-Path $targetDirectory 'pikafish.exe'
$networkTarget = Join-Path $targetDirectory 'pikafish.nnue'
$existingTargets = @($engineTarget, $networkTarget) | Where-Object { Test-Path -LiteralPath $_ }
if ($existingTargets.Count -gt 0 -and -not $Force) {
    if ($WhatIfPreference) {
        Write-Warning "目标目录已有引擎文件。预览未写入任何文件；实际更新时请加 -Force。"
    } else {
    throw "引擎文件已存在于 $targetDirectory。确认要更新时，请加 -Force。"
    }
}

$asset = $archiveAssets[0]
if (-not $PSCmdlet.ShouldProcess("$targetDirectory (Pikafish $($release.tag_name))", '下载并安装官方引擎')) {
    return
}

$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tempDirectory = [IO.Path]::GetFullPath((Join-Path $tempRoot ("pikafish-install-" + [Guid]::NewGuid().ToString('N'))))
if (-not $tempDirectory.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw '临时目录校验失败。'
}

[IO.Directory]::CreateDirectory($tempDirectory) | Out-Null
try {
    $archivePath = Join-Path $tempDirectory $asset.name
    $extractDirectory = Join-Path $tempDirectory 'extracted'
    [IO.Directory]::CreateDirectory($extractDirectory) | Out-Null

    Write-Output "下载 Pikafish $($release.tag_name)：$($asset.name)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archivePath -Headers @{ 'User-Agent' = $headers['User-Agent'] } -TimeoutSec 180
    if (-not (Test-Path -LiteralPath $archivePath) -or (Get-Item -LiteralPath $archivePath).Length -lt 1MB) {
        throw '下载文件不存在或大小异常。'
    }

    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if (-not $tar) { throw '找不到 Windows tar.exe；请使用较新的 Windows 10/11，或先安装支持 7z 的 tar。' }
    & $tar.Source -xf $archivePath -C $extractDirectory
    if ($LASTEXITCODE -ne 0) { throw "解压官方 .7z 文件失败，tar.exe 退出码：$LASTEXITCODE" }

    $engineCandidates = @(Get-ChildItem -LiteralPath $extractDirectory -Recurse -File | Where-Object { $_.Name -match '^Pikafish-Windows-x86-64-universal\.exe$' })
    $networkCandidates = @(Get-ChildItem -LiteralPath $extractDirectory -Recurse -File | Where-Object { $_.Name -ieq 'pikafish.nnue' })
    if ($engineCandidates.Count -ne 1 -or $networkCandidates.Count -ne 1) {
        throw "发布包内容与预期不符；需要 Windows x86-64 universal 引擎和一个 pikafish.nnue，未修改安装目录。"
    }
    if ($engineCandidates[0].Length -lt 1MB -or $networkCandidates[0].Length -lt 1MB) {
        throw '引擎或 NNUE 文件大小异常，未修改安装目录。'
    }

    [IO.Directory]::CreateDirectory($targetDirectory) | Out-Null
    Copy-Item -LiteralPath $engineCandidates[0].FullName -Destination $engineTarget -Force
    Copy-Item -LiteralPath $networkCandidates[0].FullName -Destination $networkTarget -Force

    Write-Output "Pikafish $($release.tag_name) 已安装："
    Write-Output "  引擎：$engineTarget"
    Write-Output "  网络：$networkTarget"
} finally {
    $resolvedTempDirectory = [IO.Path]::GetFullPath($tempDirectory)
    if ($resolvedTempDirectory.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedTempDirectory)) {
        Remove-Item -LiteralPath $resolvedTempDirectory -Recurse -Force
    }
}
