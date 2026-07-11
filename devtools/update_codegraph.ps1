$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

git -C $repoRoot rev-parse --verify HEAD *> $null
if ($LASTEXITCODE -ne 0) {
    throw "CodeGraph requires an initial Git commit. Create the repository's first commit, then run this script again."
}

$commitCount = [int](git -C $repoRoot rev-list --count HEAD)
$base = if ($commitCount -gt 1) { "HEAD~1" } else { "HEAD" }
$fullRebuild = -not (Test-Path (Join-Path $repoRoot ".codegraph\codegraph.db"))

$env:LUMINA_CODEGRAPH_ROOT = $repoRoot
$env:LUMINA_CODEGRAPH_BASE = $base
$env:LUMINA_CODEGRAPH_FULL_REBUILD = if ($fullRebuild) { "1" } else { "0" }

uvx --python 3.13 --from better-code-review-graph python -c "import json, os; from better_code_review_graph.tools import build_or_update_graph; result = build_or_update_graph(full_rebuild=os.environ['LUMINA_CODEGRAPH_FULL_REBUILD'] == '1', repo_root=os.environ['LUMINA_CODEGRAPH_ROOT'], base=os.environ['LUMINA_CODEGRAPH_BASE']); print(json.dumps(result, ensure_ascii=False, indent=2, default=str))"
if ($LASTEXITCODE -ne 0) {
    throw "CodeGraph update failed with exit code $LASTEXITCODE."
}

$database = Get-Item (Join-Path $repoRoot ".codegraph\codegraph.db")
Write-Host "CodeGraph database: $($database.FullName)"
Write-Host "Last updated: $($database.LastWriteTime)"
