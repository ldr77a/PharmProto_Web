[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [switch]$Staged
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath $Path).Path
$releaseDatabase = "release-data/knowledge.sqlite"
$releaseManifest = "release-data/manifest.json"
$forbiddenNamePatterns = @(
    '(^|/)\.env(\.|$)',
    '(^|/)__pycache__(/|$)',
    '(^|/)\.codex(/|$)',
    '(^|/)\.agents(/|$)',
    '(^|/)\.pytest_tmp_',
    '(^|/)node_modules(/|$)',
    '(^|/)outputs(/|$)',
    '(^|/)(logs|cache|updates)(/|$)',
    '\.pdf$',
    '\.(sqlite|db|dump)$',
    '\.sqlite-'
)
$secretPattern = '(?im)(?:^|[\r\n{,])\s*["'']?(api[_-]?key|secret|password|authorization|token)["'']?\s*[:=]\s*(?!["'']?\$\{?)(?!["'']?(?:REDACTED|YOUR_|EXAMPLE))(?!os\.environ|os\.getenv|process\.env|\$env:|System\.Environment)(?!self\.|cls\.)(?![A-Za-z_][A-Za-z0-9_]*(?:\s*[,)}\]]|\.|\[|\())["'']?[^\s"''][^\s"'']{7,}'
$textExtensions = @(
    ".bat", ".cmd", ".cfg", ".csv", ".cypher", ".ini", ".js", ".json", ".jsonl", ".md",
    ".mjs", ".ps1", ".py", ".sh", ".toml", ".ts", ".txt", ".yaml", ".yml"
)

function ConvertFrom-GitNulPathList {
    param([string]$Output)

    return @($Output.Split([char]0, [System.StringSplitOptions]::RemoveEmptyEntries))
}

function Get-ReleaseCandidates {
    if ($Staged) {
        if (-not (Test-Path -LiteralPath (Join-Path $root ".git"))) {
            throw "Unable to read the staged Git tree"
        }
        $staged = (& git -C $root -c core.excludesFile=.git/info/exclude -c core.quotepath=false diff --cached --name-only --diff-filter=ACMR -z 2>$null | Out-String)
        if ($LASTEXITCODE -ne 0) { throw "Unable to read the staged Git tree" }
        return ConvertFrom-GitNulPathList $staged
    }

    if (Test-Path -LiteralPath (Join-Path $root ".git")) {
        $candidates = (& git -C $root -c core.excludesFile=.git/info/exclude -c core.quotepath=false ls-files --cached --others --exclude-standard -z 2>$null | Out-String)
        if ($LASTEXITCODE -eq 0) {
            return ConvertFrom-GitNulPathList $candidates
        }
    }

    return @(Get-ChildItem -LiteralPath $root -File -Recurse | ForEach-Object {
        $_.FullName.Substring($root.Length).TrimStart('\', '/') -replace '\\', '/'
    })
}

function Test-ApprovedTextPath {
    param([string]$RelativePath)

    return $textExtensions -contains [System.IO.Path]::GetExtension($RelativePath).ToLowerInvariant()
}

function Get-ReleaseText {
    param([string]$RelativePath, [string]$FullPath)

    if ($Staged) {
        $contents = (& git -C $root show ":$RelativePath" 2>$null | Out-String)
        if ($LASTEXITCODE -ne 0) { throw "Unable to read staged blob: $RelativePath" }
        return $contents
    }

    return [System.IO.File]::ReadAllText($FullPath, [System.Text.Encoding]::UTF8)
}

$violations = [System.Collections.Generic.List[string]]::new()
foreach ($candidate in Get-ReleaseCandidates) {
    if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
    $relative = $candidate -replace '\\', '/'
    $normalized = $relative.ToLowerInvariant()
    $fullPath = Join-Path $root ($relative -replace '/', '\\')

    if ($normalized -eq $releaseDatabase -or $normalized -eq $releaseManifest) { continue }
    foreach ($pattern in $forbiddenNamePatterns) {
        if ($normalized -match $pattern) {
            $violations.Add("Forbidden release file: $relative")
            break
        }
    }

    if (Test-ApprovedTextPath $relative) {
        try {
            $contents = Get-ReleaseText $relative $fullPath
            if ($contents -match $secretPattern) {
                $violations.Add("Secret-shaped content: $relative")
            }
        }
        catch [System.Text.DecoderFallbackException] {
            # Binary files are checked by their names, not decoded as text.
        }
    }
}

if ($violations.Count -gt 0) {
    $violations | Sort-Object -Unique | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Host "Release-tree audit passed ($(@(Get-ReleaseCandidates).Count) candidate files)."
