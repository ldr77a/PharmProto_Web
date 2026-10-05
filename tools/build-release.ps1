[CmdletBinding()]
param(
    [string]$DatabasePath = "release-data/knowledge.sqlite",
    [string]$ManifestPath = "release-data/manifest.json",
    [string]$OutputDirectory = "dist"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("PhramaProto-release-" + [guid]::NewGuid().ToString("N"))
$temporaryZip = $null

function Resolve-ProjectRelativePath {
    param([string]$Value)
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return (Resolve-Path -LiteralPath $Value).Path
    }
    return (Resolve-Path -LiteralPath (Join-Path $ProjectRoot $Value)).Path
}

function Copy-ReleaseFile {
    param([string]$Source, [string]$RelativePath)
    $target = Join-Path $stagingRoot $RelativePath
    $parent = Split-Path -Parent $target
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Copy-Item -LiteralPath $Source -Destination $target -Force
}

try {
    $database = Resolve-ProjectRelativePath $DatabasePath
    $manifest = Resolve-ProjectRelativePath $ManifestPath
    $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "verified build Python is unavailable"
    }

    Push-Location -LiteralPath $ProjectRoot
    try {
        & $python -m pharma_proto.cli verify-snapshot --database $database --manifest $manifest | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "snapshot verification failed" }
    }
    finally {
        Pop-Location
    }

    $manifestData = Get-Content -LiteralPath $manifest -Raw -Encoding utf8 | ConvertFrom-Json
    $snapshotId = [string]$manifestData.snapshot_id
    if ([string]::IsNullOrWhiteSpace($snapshotId)) { throw "snapshot id is missing" }
    $safeSnapshotId = $snapshotId -replace '[^A-Za-z0-9._-]', '_'
    if ([string]::IsNullOrWhiteSpace($safeSnapshotId)) { throw "snapshot id is invalid" }

    $versionSource = Get-Content -LiteralPath (Join-Path $ProjectRoot "pharma_proto\__init__.py") -Raw -Encoding utf8
    $versionMatch = [regex]::Match($versionSource, '__version__\s*=\s*["''](?<version>[^"'']+)["'']')
    if (-not $versionMatch.Success) { throw "application version is missing" }
    $appVersion = $versionMatch.Groups["version"].Value

    New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
    $rootFiles = @(
        "start.bat",
        "pyproject.toml",
        "uv.lock",
        "function_seed.json",
        "README-RESEARCHER.md"
    )
    foreach ($relative in $rootFiles) {
        $source = Join-Path $ProjectRoot $relative
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "required source file is missing" }
        Copy-ReleaseFile -Source $source -RelativePath $relative
    }

    $runtimePackageFiles = @(
        "pharma_proto\__init__.py",
        "pharma_proto\app.py",
        "pharma_proto\conversation.py",
        "pharma_proto\diagnostics.py",
        "pharma_proto\errors.py",
        "pharma_proto\excel_export.py",
        "pharma_proto\instance_lock.py",
        "pharma_proto\launcher.py",
        "pharma_proto\preferences.py",
        "pharma_proto\results_store.py",
        "pharma_proto\knowledge\__init__.py",
        "pharma_proto\knowledge\contracts.py",
        "pharma_proto\knowledge\evidence.py",
        "pharma_proto\knowledge\function_taxonomy.py",
        "pharma_proto\knowledge\snapshot.py",
        "pharma_proto\knowledge\sqlite_repository.py",
        "pharma_proto\llm\__init__.py",
        "pharma_proto\llm\catalog.py",
        "pharma_proto\llm\memory_keys.py",
        "pharma_proto\llm\resilience.py",
        "pharma_proto\llm\schema.py",
        "pharma_proto\llm\service.py",
        "pharma_proto\static\app.css",
        "pharma_proto\static\app.js",
        "pharma_proto\static\favicon.svg",
        "pharma_proto\static\paper.svg",
        "pharma_proto\static\fonts\PretendardVariable.woff2",
        "pharma_proto\static\fonts\OFL.txt",
        "pharma_proto\templates\index.html",
        "generation\__init__.py",
        "generation\candidate_selector.py",
        "generation\dose_resolver.py",
        "generation\excipient_allocator.py",
        "generation\explanation.py",
        "generation\generation_loop.py",
        "generation\help_text.py",
        "generation\html_formatter.py",
        "generation\input_parser.py",
        "generation\oral_solid_profiles.py",
        "generation\standard_doses.json",
        "gates\__init__.py",
        "gates\allowable_range.py",
        "gates\compatibility.py",
        "gates\formulation.py",
        "gates\function_coverage.py",
        "gates\kg_util.py",
        "gates\manufacturability.py",
        "gates\pipeline.py",
        "gates\rule_data.py",
        "gates\smiles_resolver.py",
        "gates\total_constraint.py",
        "gates\total_sum.py",
        "cleaning\__init__.py",
        "cleaning\canonical_base.py"
    )
    foreach ($relative in $runtimePackageFiles) {
        $source = Join-Path $ProjectRoot $relative
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "required runtime file is missing" }
        Copy-ReleaseFile -Source $source -RelativePath $relative
    }

    foreach ($relative in @("tools\bootstrap-runtime.ps1", "tools\uv-windows-x64.sha256")) {
        Copy-ReleaseFile -Source (Join-Path $ProjectRoot $relative) -RelativePath $relative
    }

    $runtimeProjectPath = Join-Path $stagingRoot "pyproject.toml"
    $projectText = [System.IO.File]::ReadAllText($runtimeProjectPath, [System.Text.Encoding]::UTF8)
    # 앱 저장소의 pyproject 는 이미 런타임 패키지 목록이다(normalization 은 DB 저장소 소유). 선언 존재만 확인한다.
    $sourcePackages = 'packages = ["pharma_proto", "generation", "gates", "cleaning"]'
    $runtimePackages = 'packages = ["pharma_proto", "generation", "gates", "cleaning"]'
    if (-not $projectText.Contains($sourcePackages)) {
        throw "runtime package declaration is missing"
    }
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText(
        $runtimeProjectPath,
        $projectText.Replace($sourcePackages, $runtimePackages),
        $utf8NoBom
    )
    Copy-ReleaseFile -Source $database -RelativePath "release-data\knowledge.sqlite"
    Copy-ReleaseFile -Source $manifest -RelativePath "release-data\manifest.json"

    & (Join-Path $ProjectRoot "tools\check-release-tree.ps1") -Path $stagingRoot
    if ($LASTEXITCODE -ne 0) { throw "release audit failed" }

    $outputRoot = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
        [System.IO.Path]::GetFullPath($OutputDirectory)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutputDirectory))
    }
    New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
    $archiveName = "PhramaProto-$appVersion-$safeSnapshotId.zip"
    $archivePath = Join-Path $outputRoot $archiveName
    $temporaryZip = Join-Path $outputRoot ("." + $archiveName + "." + [guid]::NewGuid().ToString("N") + ".tmp.zip")
    Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $temporaryZip -CompressionLevel Optimal
    Move-Item -LiteralPath $temporaryZip -Destination $archivePath -Force
    $temporaryZip = $null
    Write-Host $archivePath
    exit 0
}
catch {
    Write-Verbose ("release build failed: " + $_.Exception.Message)
    Write-Error "RELEASE-BUILD-001"
    exit 1
}
finally {
    if ($temporaryZip -and (Test-Path -LiteralPath $temporaryZip -PathType Leaf)) {
        Remove-Item -LiteralPath $temporaryZip -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $stagingRoot -PathType Container) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
