[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$UvVersion = "0.12.0"
$PythonVersion = "3.12.13"
$archiveName = "uv-x86_64-pc-windows-msvc.zip"
$releaseUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$archiveName"
$expectedHashPath = Join-Path $PSScriptRoot "uv-windows-x64.sha256"

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "APP-START-001 LOCALAPPDATA is required"
}

$appRoot = Join-Path $env:LOCALAPPDATA "PharmaProto"
$toolsRoot = Join-Path $appRoot "tools"
$logsRoot = Join-Path $appRoot "logs"
$logPath = Join-Path $logsRoot "bootstrap.log"
$uvExe = Join-Path $toolsRoot "uv.exe"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("PharmaProto-bootstrap-" + [guid]::NewGuid().ToString("N"))
$env:UV_PROJECT_ENVIRONMENT = Join-Path $appRoot "runtime\venv"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $appRoot "runtime\python"
$env:UV_CACHE_DIR = Join-Path $appRoot "runtime\uv-cache"

function Redact-Message {
    param([string]$Message)

    $redacted = $Message -replace '(?i)(authorization|token|password|api[_-]?key)\s*[:=]\s*\S+', '$1=[REDACTED]'
    $redacted = $redacted -replace [regex]::Escape($env:USERPROFILE), "[USERPROFILE]"
    return $redacted.Substring(0, [Math]::Min($redacted.Length, 500))
}

function Write-BootstrapLog {
    param([string]$Phase, [string]$Message)

    New-Item -ItemType Directory -Force -Path $logsRoot | Out-Null
    $line = "{0:o} [{1}] {2}" -f (Get-Date).ToUniversalTime(), $Phase, (Redact-Message $Message)
    Add-Content -LiteralPath $logPath -Value $line -Encoding utf8
}

function Test-PinnedUv {
    if (-not (Test-Path -LiteralPath $uvExe -PathType Leaf)) {
        return $false
    }

    $version = (& $uvExe --version 2>&1 | Out-String).Trim()
    return $LASTEXITCODE -eq 0 -and $version -like "uv $UvVersion*"
}

try {
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "pyproject.toml") -PathType Leaf)) {
        throw "APP-START-001 pyproject.toml is missing"
    }

    New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
    Write-BootstrapLog "bootstrap" "Starting verified uv $UvVersion bootstrap"

    if (-not (Test-PinnedUv)) {
        New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
        $archivePath = Join-Path $tempRoot $archiveName
        $officialHashPath = "$archivePath.sha256"
        $extractRoot = Join-Path $tempRoot "extract"

        Write-BootstrapLog "download" "Downloading uv archive and checksum"
        Invoke-WebRequest -UseBasicParsing -Uri $releaseUrl -OutFile $archivePath
        Invoke-WebRequest -UseBasicParsing -Uri "$releaseUrl.sha256" -OutFile $officialHashPath

        $committedHash = ((Get-Content -LiteralPath $expectedHashPath -Raw).Trim().Split([char[]]" `t")[0]).ToLowerInvariant()
        $officialHash = ((Get-Content -LiteralPath $officialHashPath -Raw).Trim().Split([char[]]" `t")[0]).ToLowerInvariant()
        $archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($archiveHash -ne $officialHash -or $archiveHash -ne $committedHash) {
            throw "APP-START-001 uv checksum verification failed"
        }

        Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot -Force
        $extractedUv = Join-Path $extractRoot "uv.exe"
        if (-not (Test-Path -LiteralPath $extractedUv -PathType Leaf)) {
            throw "APP-START-001 uv archive did not contain uv.exe"
        }

        Move-Item -LiteralPath $extractedUv -Destination $uvExe -Force
    }

    if (-not (Test-PinnedUv)) {
        throw "APP-START-001 verified uv $UvVersion is unavailable"
    }

    Push-Location -LiteralPath $ProjectRoot
    try {
        Write-BootstrapLog "python" "Installing managed CPython $PythonVersion"
        & $uvExe python install $PythonVersion
        if ($LASTEXITCODE -ne 0) { throw "APP-START-001 Python installation failed" }

        Write-BootstrapLog "sync" "Synchronizing locked dependencies"
        & $uvExe sync --frozen --no-dev --python $PythonVersion
        if ($LASTEXITCODE -ne 0) { throw "APP-START-001 dependency sync failed" }
    }
    finally {
        Pop-Location
    }

    Write-BootstrapLog "complete" "Bootstrap completed"
    exit 0
}
catch {
    Write-BootstrapLog "error" "APP-START-001 $(Redact-Message $_.Exception.Message)"
    exit 1
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
