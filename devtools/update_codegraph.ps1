$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$databasePath = Join-Path $repoRoot ".codegraph\codegraph.db"
$codegraph = Get-Command codegraph -ErrorAction SilentlyContinue
if (-not $codegraph) {
    throw "CodeGraph CLI was not found. Install it before updating the project index."
}

if (Test-Path -LiteralPath $databasePath) {
    $statusJson = & $codegraph.Source status --json $repoRoot
    if ($LASTEXITCODE -ne 0) {
        throw "CodeGraph pre-update status check failed with exit code $LASTEXITCODE."
    }

    try {
        $status = ($statusJson -join [Environment]::NewLine) | ConvertFrom-Json
    } catch {
        throw "CodeGraph pre-update status returned invalid JSON: $($_.Exception.Message)"
    }

    if ($status.index -and $status.index.reindexRecommended -eq $true) {
        Write-Host "CodeGraph extraction version changed; rebuilding the project index."
        & $codegraph.Source index $repoRoot
    } else {
        & $codegraph.Source sync $repoRoot
    }
} else {
    & $codegraph.Source init -i $repoRoot
}

if ($LASTEXITCODE -ne 0) {
    throw "CodeGraph update failed with exit code $LASTEXITCODE."
}

& $codegraph.Source status --json $repoRoot
if ($LASTEXITCODE -ne 0) {
    throw "CodeGraph status check failed with exit code $LASTEXITCODE."
}

if (Test-Path $databasePath) {
    $database = Get-Item $databasePath
    Write-Host "CodeGraph database: $($database.FullName)"
    Write-Host "Last updated: $($database.LastWriteTime)"
} else {
    Write-Warning "No supported source files were found. The CodeGraph database will be created after Python or TypeScript source files are added."
}
