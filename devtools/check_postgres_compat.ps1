[CmdletBinding()]
param(
    [switch]$Connect,
    [string]$EnvFile
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ServerRoot = Join-Path $RepositoryRoot "apps/server"
. (Join-Path $PSScriptRoot "LuminaCache.Env.ps1") -RepositoryRoot $RepositoryRoot
$ResolvedEnvFile = if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    Join-Path $RepositoryRoot ".env"
}
else {
    $EnvFile
}

if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    throw "Required command 'uv' was not found on PATH."
}

$arguments = @(
    "run", "--offline", "--project", $ServerRoot,
    "python", "-m", "lumina.diagnostics",
    "--repo-root", $RepositoryRoot,
    "--database", "--require-postgres"
)
if ($Connect) {
    $arguments += @("--env-file", $ResolvedEnvFile)
    $arguments += "--network"
}
else {
    # Dotenv values intentionally take precedence in Lumina. Omit the user's
    # env file so this compile-only URL reaches the diagnostics process.
    $arguments += "--no-env-file"
    $env:DATABASE_URL = "postgresql+psycopg://lumina:offline@127.0.0.1/lumina"
    $arguments += "--no-network"
}

& uv @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL compatibility diagnostics failed with exit code $LASTEXITCODE."
}
