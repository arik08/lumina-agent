param(
    [Parameter(Mandatory = $true)][string]$RepositoryRoot
)

$cacheRoot = Join-Path $RepositoryRoot ".cache"
$env:PYTHONPYCACHEPREFIX = Join-Path $cacheRoot "pycache"
$env:MYPY_CACHE_DIR = Join-Path $cacheRoot "mypy"
$env:RUFF_CACHE_DIR = Join-Path $cacheRoot "ruff"
$env:PYTEST_ADDOPTS = "-o cache_dir=`"$(Join-Path $cacheRoot 'pytest')`""
