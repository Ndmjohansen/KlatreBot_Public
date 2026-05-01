<#
.SYNOPSIS
  Download Litestream for Windows, render a working config, optionally start it.

.DESCRIPTION
  - Fetches latest Litestream release zip from GitHub.
  - Extracts litestream.exe into <repo>/infra/litestream/bin/.
  - Generates infra/litestream/litestream-windows.local.yml from the template,
    substituting -DestHost / -DestUser / repo path / -SshKey.
  - Optionally launches `litestream replicate` in this terminal.

  Re-runnable. Existing files are overwritten (binary) or skipped (config).

.PARAMETER DestHost
  Ubuntu LAN IP.

.PARAMETER DestUser
  SSH user on Ubuntu (typically 'hermes' once that account exists).

.PARAMETER SshKey
  Absolute path to your SSH private key (no passphrase, since Litestream runs
  unattended). Default: $env:USERPROFILE\.ssh\litestream_id_ed25519

.PARAMETER Run
  After install + render, immediately start `litestream replicate` in foreground.

.EXAMPLE
  .\install-litestream-windows.ps1 -DestHost 192.168.1.42 -DestUser hermes -Run
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$DestHost,
    [Parameter(Mandatory)] [string]$DestUser,
    [string]$SshKey = (Join-Path $env:USERPROFILE '.ssh\litestream_id_ed25519'),
    [switch]$Run
)

$ErrorActionPreference = 'Stop'

$infraDir = $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $infraDir)
$binDir   = Join-Path $infraDir 'bin'
$exePath  = Join-Path $binDir 'litestream.exe'
$tmpl     = Join-Path $infraDir 'litestream-windows.yml'
$rendered = Join-Path $infraDir 'litestream-windows.local.yml'

# 1. Download Litestream binary if missing
if (-not (Test-Path $exePath)) {
    Write-Host "Fetching latest Litestream release..." -ForegroundColor Cyan
    $api = Invoke-RestMethod 'https://api.github.com/repos/benbjohnson/litestream/releases/latest'
    $asset = $api.assets | Where-Object { $_.name -match 'windows.*amd64.*\.zip$' } | Select-Object -First 1
    if (-not $asset) { throw "no windows-amd64 zip in latest release" }
    $zipPath = Join-Path $env:TEMP $asset.name
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
    Expand-Archive -Path $zipPath -DestinationPath $binDir -Force
    Remove-Item $zipPath
    Write-Host "Installed: $exePath" -ForegroundColor Green
} else {
    Write-Host "litestream.exe already present at $exePath" -ForegroundColor DarkGray
}

# 2. Render config
if (-not (Test-Path $tmpl)) { throw "template missing: $tmpl" }
if (-not (Test-Path $SshKey)) {
    Write-Warning "SSH key not found at $SshKey — generate one with:"
    Write-Warning "  ssh-keygen -t ed25519 -N '""""' -f `"$SshKey`""
    Write-Warning "Then append the .pub to ${DestUser}@${DestHost}:~/.ssh/authorized_keys"
}

$repoFwd = $repoRoot -replace '\\', '/'
$keyFwd  = $SshKey -replace '\\', '/'

(Get-Content $tmpl -Raw) `
    -replace '<UBUNTU_LAN_IP>', $DestHost `
    -replace '<UBUNTU_USER>', $DestUser `
    -replace '<REPO_PATH>', $repoFwd `
    -replace '<SSH_KEY_PATH>', $keyFwd `
    | Set-Content -Path $rendered -Encoding utf8

Write-Host "Rendered config: $rendered" -ForegroundColor Green

# 3. Optionally run
if ($Run) {
    Write-Host ""
    Write-Host "Starting Litestream (Ctrl+C to stop)..." -ForegroundColor Cyan
    & $exePath replicate -config $rendered
} else {
    Write-Host ""
    Write-Host "To start replication run:" -ForegroundColor Yellow
    Write-Host "  & '$exePath' replicate -config '$rendered'" -ForegroundColor White
}
