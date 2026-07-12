[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [switch]$ConfigurePgpt,
    [switch]$SkipPgpt,
    [string]$CompanyCaPath,
    [switch]$RequireCompanyCa,
    [switch]$PgptNetworkCheck,
    [switch]$NoNetwork,
    [switch]$ValidateOnly,
    [switch]$SkipDependencyInstall,
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ServerRoot = Join-Path $RepositoryRoot "apps/server"
$WebRoot = Join-Path $RepositoryRoot "apps/web"
$EnvFile = Join-Path $RepositoryRoot ".env"
. (Join-Path $PSScriptRoot "LuminaCache.Env.ps1") -RepositoryRoot $RepositoryRoot
. (Join-Path $PSScriptRoot "LuminaInstall.Env.ps1")

function Assert-Command {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$InstallHint
    )
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH. $InstallHint After installing it, close this window, open a new terminal, and run installer.bat again."
    }
}

function Assert-NodeVersion {
    $rawVersion = (& node --version 2>$null).Trim().TrimStart("v")
    $parsedVersion = $null
    if (-not [version]::TryParse($rawVersion, [ref]$parsedVersion)) {
        throw "Could not determine the installed Node.js version. Reinstall the current Node.js LTS from https://nodejs.org/en/download and run installer.bat again."
    }
    $minimumVersion = [version]"20.19.0"
    if ($parsedVersion -lt $minimumVersion) {
        throw "Node.js 20.19.0 or newer is required by the frontend build, but $parsedVersion is installed. Install the current Node.js LTS from https://nodejs.org/en/download and run installer.bat again."
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        # Arguments may contain paths or future sensitive values. Do not echo them.
        throw "Command '$Command' failed with exit code $LASTEXITCODE."
    }
}

function Get-ConfiguredValue {
    param([Parameter(Mandatory = $true)][string]$Key)
    $processValue = [Environment]::GetEnvironmentVariable($Key, "Process")
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue
    }
    return Get-LuminaDotEnvValue -Path $EnvFile -Key $Key
}

function ConvertFrom-SecureValue {
    param([Parameter(Mandatory = $true)][Security.SecureString]$Value)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Get-RequiredSecretSetting {
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Prompt
    )
    $existing = Get-ConfiguredValue -Key $Key
    if (-not [string]::IsNullOrWhiteSpace($existing)) {
        return $existing
    }
    if ($NonInteractive) {
        throw "P-GPT setup requires '$Key' through the process environment or existing .env."
    }
    $secure = Read-Host $Prompt -AsSecureString
    $plain = ConvertFrom-SecureValue -Value $secure
    if ([string]::IsNullOrWhiteSpace($plain)) {
        throw "P-GPT setup requires '$Key'."
    }
    return $plain
}

function Resolve-ConfiguredPath {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    $candidate = [Environment]::ExpandEnvironmentVariables($PathValue)
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $RepositoryRoot $candidate
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Configured certificate or bundle file does not exist."
    }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Set-TrustEnvironment {
    param([Parameter(Mandatory = $true)][string]$BundlePath)
    $env:SSL_CERT_FILE = $BundlePath
    $env:REQUESTS_CA_BUNDLE = $BundlePath
    $env:CURL_CA_BUNDLE = $BundlePath
    $env:PIP_CERT = $BundlePath
    $env:NODE_EXTRA_CA_CERTS = $BundlePath
    $env:npm_config_cafile = $BundlePath
}

if ($ConfigurePgpt -and $SkipPgpt) {
    throw "ConfigurePgpt and SkipPgpt cannot be used together."
}
if ($PgptNetworkCheck -and $NoNetwork) {
    throw "PgptNetworkCheck and NoNetwork cannot be used together."
}

Set-Location -LiteralPath $RepositoryRoot
Write-Host "[Lumina] Checking required tools..."
Assert-Command "uv" "Install uv with: powershell -ExecutionPolicy Bypass -c `"irm https://astral.sh/uv/install.ps1 | iex`"."
Assert-Command "node" "Install the current Node.js LTS from https://nodejs.org/en/download."
Assert-Command "npm" "npm is included with Node.js; reinstall the current Node.js LTS from https://nodejs.org/en/download."
Assert-NodeVersion
$NpmCommand = if ($env:OS -eq "Windows_NT") {
    (Get-Command "npm.cmd" -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
}
else {
    (Get-Command "npm" -ErrorAction Stop | Select-Object -First 1).Source
}
Write-Host "[Lumina] Required tools are available."

if ($ValidateOnly) {
    if ($PgptNetworkCheck) {
        throw "ValidateOnly never performs network diagnostics."
    }
    $validationEnvFile = if (Test-Path -LiteralPath $EnvFile) {
        $EnvFile
    }
    else {
        Join-Path $RepositoryRoot ".env.example"
    }
    $validationArguments = @(
        "run", "--offline", "--project", $ServerRoot,
        "python", "-m", "lumina.diagnostics",
        "--repo-root", $RepositoryRoot,
        "--env-file", $validationEnvFile,
        "--no-network"
    )
    if ($ConfigurePgpt) {
        $validationArguments += "--pgpt"
    }
    if ($RequireCompanyCa) {
        $validationArguments += "--require-company-ca"
    }
    if (-not [string]::IsNullOrWhiteSpace($CompanyCaPath)) {
        $validationCa = Resolve-ConfiguredPath -PathValue $CompanyCaPath
        $validationArguments += @("--company-ca", $validationCa)
    }
    $validationRuntime = Join-Path ([System.IO.Path]::GetTempPath()) ("lumina-trust-" + [guid]::NewGuid().ToString("N"))
    $validationArguments += @("--trust-runtime-dir", $validationRuntime)
    Write-Host "[Lumina] Validating installer prerequisites without changing files or using the network..."
    try {
        Invoke-Checked -Command "uv" -Arguments $validationArguments
    }
    finally {
        if (Test-Path -LiteralPath $validationRuntime) {
            Remove-Item -LiteralPath $validationRuntime -Recurse -Force
        }
    }
    Write-Host "[Lumina] Installer validation completed."
    return
}

foreach ($path in @(
    "data/database",
    "data/files",
    "data/artifacts",
    "data/logs",
    "data/certs",
    "data/certs/runtime"
)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $RepositoryRoot $path) | Out-Null
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath (Join-Path $RepositoryRoot ".env.example") -Destination $EnvFile
    Write-Host "[Lumina] Created .env from .env.example."
}

$enablePgpt = [bool]$ConfigurePgpt
if (-not $ConfigurePgpt -and -not $SkipPgpt -and -not $NonInteractive) {
    $choice = Read-Host "Configure the optional P-GPT provider now? [y/N]"
    $enablePgpt = $choice -match '^(?i)y(?:es)?$'
}

if ($enablePgpt) {
    Write-Host "[Lumina] Configuring P-GPT credentials without displaying their values..."
    $pgptApiKey = Get-RequiredSecretSetting -Key "PGPT_API_KEY" -Prompt "P-GPT API key"
    $pgptEmployeeNo = Get-RequiredSecretSetting -Key "PGPT_EMPLOYEE_NO" -Prompt "P-GPT employee number"
    $pgptCompanyCode = Get-RequiredSecretSetting -Key "PGPT_COMPANY_CODE" -Prompt "P-GPT company code"
    try {
        Set-LuminaDotEnvValue -Path $EnvFile -Key "PGPT_API_KEY" -Value $pgptApiKey
        Set-LuminaDotEnvValue -Path $EnvFile -Key "PGPT_EMPLOYEE_NO" -Value $pgptEmployeeNo
        Set-LuminaDotEnvValue -Path $EnvFile -Key "PGPT_COMPANY_CODE" -Value $pgptCompanyCode
    }
    finally {
        $pgptApiKey = $null
        $pgptEmployeeNo = $null
        $pgptCompanyCode = $null
    }
}

$selectedCa = $CompanyCaPath
if ([string]::IsNullOrWhiteSpace($selectedCa)) {
    $selectedCa = Get-ConfiguredValue -Key "LUMINA_CA_CERT"
}
if ([string]::IsNullOrWhiteSpace($selectedCa)) {
    foreach ($candidate in @(
        (Join-Path $RepositoryRoot "data/certs/company-ca.crt"),
        "C:/POSCO_CA.crt"
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $selectedCa = $candidate
            break
        }
    }
}
if ([string]::IsNullOrWhiteSpace($selectedCa) -and -not $NonInteractive) {
    $selectedCa = Read-Host "Company CA path (leave blank to use public CA only)"
}

$resolvedCa = ""
if (-not [string]::IsNullOrWhiteSpace($selectedCa)) {
    $selectedCaCandidate = [Environment]::ExpandEnvironmentVariables($selectedCa)
    if (-not [System.IO.Path]::IsPathRooted($selectedCaCandidate)) {
        $selectedCaCandidate = Join-Path $RepositoryRoot $selectedCaCandidate
    }
    if (-not (Test-Path -LiteralPath $selectedCaCandidate -PathType Leaf) -and
        [string]::IsNullOrWhiteSpace($CompanyCaPath) -and
        -not $RequireCompanyCa) {
        Write-Warning "Saved company CA path was not found. Continuing with public CA trust."
    }
    else {
        $resolvedCa = Resolve-ConfiguredPath -PathValue $selectedCa
        if (-not [string]::IsNullOrWhiteSpace($CompanyCaPath) -or
            [string]::IsNullOrWhiteSpace((Get-LuminaDotEnvValue -Path $EnvFile -Key "LUMINA_CA_CERT"))) {
            Set-LuminaDotEnvValue -Path $EnvFile -Key "LUMINA_CA_CERT" -Value $resolvedCa
        }
    }
}
elseif ($RequireCompanyCa) {
    throw "A company CA is required but no certificate path was configured or discovered."
}

if (-not $SkipDependencyInstall) {
    Write-Host "[Lumina] Installing Python dependencies..."
    $pythonInstallArguments = @("sync", "--project", $ServerRoot, "--python", "3.13")
    if ($NoNetwork) {
        $pythonInstallArguments += "--offline"
    }
    Invoke-Checked -Command "uv" -Arguments $pythonInstallArguments
}

$staticArguments = @("run")
if ($NoNetwork) {
    $staticArguments += "--offline"
}
$staticArguments += @(
    "--project", $ServerRoot,
    "python", "-m", "lumina.diagnostics",
    "--repo-root", $RepositoryRoot,
    "--env-file", $EnvFile,
    "--no-network"
)
if ($enablePgpt) {
    $staticArguments += "--pgpt"
}
if ($RequireCompanyCa) {
    $staticArguments += "--require-company-ca"
}
if (-not [string]::IsNullOrWhiteSpace($resolvedCa)) {
    $staticArguments += @("--company-ca", $resolvedCa)
}
Write-Host "[Lumina] Validating CA trust and static provider configuration..."
Invoke-Checked -Command "uv" -Arguments $staticArguments

$resolvedBundle = ""
if (-not [string]::IsNullOrWhiteSpace($resolvedCa)) {
    $resolvedBundle = Join-Path $RepositoryRoot "data/certs/runtime/combined-ca.pem"
    if (-not (Test-Path -LiteralPath $resolvedBundle -PathType Leaf)) {
        throw "Combined CA bundle was not generated."
    }
    Set-LuminaDotEnvValue -Path $EnvFile -Key "LUMINA_CA_BUNDLE" -Value $resolvedBundle
}
else {
    $configuredBundle = Get-ConfiguredValue -Key "LUMINA_CA_BUNDLE"
    if (-not [string]::IsNullOrWhiteSpace($configuredBundle)) {
        $configuredBundleCandidate = [Environment]::ExpandEnvironmentVariables($configuredBundle)
        if (-not [System.IO.Path]::IsPathRooted($configuredBundleCandidate)) {
            $configuredBundleCandidate = Join-Path $RepositoryRoot $configuredBundleCandidate
        }
        if (Test-Path -LiteralPath $configuredBundleCandidate -PathType Leaf) {
            $resolvedBundle = (Resolve-Path -LiteralPath $configuredBundleCandidate).Path
        }
        elseif ($RequireCompanyCa) {
            throw "Configured certificate or bundle file does not exist."
        }
        else {
            Write-Warning "Saved combined CA bundle was not found. Continuing with public CA trust."
        }
    }
}
if (-not [string]::IsNullOrWhiteSpace($resolvedBundle)) {
    Set-TrustEnvironment -BundlePath $resolvedBundle
}

if (-not $SkipDependencyInstall) {
    Write-Host "[Lumina] Installing frontend dependencies..."
    $frontendInstallArguments = @("ci", "--prefix", $WebRoot)
    if ($NoNetwork) {
        $frontendInstallArguments += @("--offline", "--no-audit")
    }
    Invoke-Checked -Command $NpmCommand -Arguments $frontendInstallArguments
}

Write-Host "[Lumina] Applying database migrations..."
$migrationArguments = @("run")
if ($NoNetwork) {
    $migrationArguments += "--offline"
}
$migrationArguments += @(
    "--project", $ServerRoot,
    "alembic", "-c", (Join-Path $ServerRoot "alembic.ini"),
    "upgrade", "head"
)
Invoke-Checked -Command "uv" -Arguments $migrationArguments

if (-not $SkipFrontendBuild) {
    Write-Host "[Lumina] Building the frontend..."
    Invoke-Checked -Command $NpmCommand -Arguments @("run", "build", "--prefix", $WebRoot)
}

$runPgptNetworkCheck = [bool]$PgptNetworkCheck
if ($enablePgpt -and -not $NonInteractive -and -not $NoNetwork -and -not $PgptNetworkCheck) {
    $choice = Read-Host "Run the opt-in P-GPT connection diagnostic now? [y/N]"
    $runPgptNetworkCheck = $choice -match '^(?i)y(?:es)?$'
}
if ($runPgptNetworkCheck) {
    Write-Host "[Lumina] Running opt-in P-GPT network diagnostics..."
    Invoke-Checked -Command "uv" -Arguments @(
        "run", "--project", $ServerRoot,
        "python", "-m", "lumina.diagnostics",
        "--repo-root", $RepositoryRoot,
        "--env-file", $EnvFile,
        "--network", "--pgpt"
    )
}

Write-Host "[Lumina] Installation completed. Run run_lumina_dev.bat for development or run_lumina.bat for the local service."
