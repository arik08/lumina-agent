[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [switch]$ConfigurePgpt,
    [switch]$SkipPgpt,
    [switch]$InstallCodex,
    [switch]$SkipCodex,
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
$WeatherMcpRoot = Join-Path $RepositoryRoot "extensions/mcp/korea_weather"
$EnvFile = Join-Path $RepositoryRoot ".env"
. (Join-Path $PSScriptRoot "LuminaCache.Env.ps1") -RepositoryRoot $RepositoryRoot
. (Join-Path $PSScriptRoot "LuminaInstall.Env.ps1")
. (Join-Path $PSScriptRoot "LuminaInstall.Frontend.ps1")

function Assert-Command {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$InstallHint
    )
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH. $InstallHint After installing it, close this window, open a new terminal, and run installer.bat again."
    }
}

function Install-UvIfMissing {
    if (Get-Command "uv" -ErrorAction SilentlyContinue) {
        return
    }
    $manualCommand = 'powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    if ($NoNetwork) {
        throw "uv was not found on PATH and cannot be installed while -NoNetwork is active. Connect to the internet and run installer.bat again, or install uv manually with: $manualCommand"
    }
    if ($env:OS -ne "Windows_NT") {
        throw "uv was not found on PATH. Install it manually with: $manualCommand"
    }

    $installDirectory = if ([string]::IsNullOrWhiteSpace($env:UV_INSTALL_DIR)) {
        Join-Path $HOME ".local\bin"
    }
    else {
        [Environment]::ExpandEnvironmentVariables($env:UV_INSTALL_DIR)
    }
    $env:UV_INSTALL_DIR = $installDirectory
    Write-Host "[Lumina] uv was not found. Installing it with the official Astral installer..."
    try {
        $installScript = Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1"
        Invoke-Expression $installScript
    }
    catch {
        throw "Automatic uv installation failed. Check the network or company certificate settings, then run installer.bat again. Manual command: $manualCommand"
    }

    $uvExecutable = Join-Path $installDirectory "uv.exe"
    if (-not (Test-Path -LiteralPath $uvExecutable -PathType Leaf)) {
        throw "The uv installer completed, but uv.exe was not found at '$installDirectory'. Open a new terminal and run installer.bat again. Manual command: $manualCommand"
    }
    $env:PATH = "$installDirectory;$env:PATH"
    Write-Host "[Lumina] uv installed successfully."
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

function Enable-UvSystemCertificates {
    $env:UV_SYSTEM_CERTS = "true"
    Write-Host "[Lumina] uv will use the operating system certificate store."
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
    param(
        [Parameter(Mandatory = $true)][string]$BundlePath,
        [string]$CompanyCaPath,
        [switch]$TlsCompatMode
    )
    $env:SSL_CERT_FILE = $BundlePath
    $env:REQUESTS_CA_BUNDLE = $BundlePath
    $env:CURL_CA_BUNDLE = $BundlePath
    $env:PIP_CERT = $BundlePath
    $env:NODE_EXTRA_CA_CERTS = if ([string]::IsNullOrWhiteSpace($CompanyCaPath)) {
        $BundlePath
    }
    else {
        $CompanyCaPath
    }
    $env:npm_config_cafile = $BundlePath
    if ($TlsCompatMode) {
        $cipherOption = "--tls-cipher-list=DEFAULT@SECLEVEL=1"
        if (($env:NODE_OPTIONS -split '\s+') -notcontains $cipherOption) {
            $env:NODE_OPTIONS = (($env:NODE_OPTIONS, $cipherOption) -join " ").Trim()
        }
    }
}

function Read-LuminaYesNoChoice {
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [scriptblock]$ReadKey = { [Console]::ReadKey($true) }
    )

    Write-Host -NoNewline "$Prompt [Y/N] "
    while ($true) {
        $key = & $ReadKey
        $keyName = [string]$key.Key
        $keyCharacter = [string]$key.KeyChar
        if (
            $keyName.Equals("Y", [StringComparison]::OrdinalIgnoreCase) -or
            $keyCharacter.Equals("y", [StringComparison]::OrdinalIgnoreCase)
        ) {
            Write-Host "Y"
            return $true
        }
        if (
            $keyName.Equals("N", [StringComparison]::OrdinalIgnoreCase) -or
            $keyCharacter.Equals("n", [StringComparison]::OrdinalIgnoreCase)
        ) {
            Write-Host "N"
            return $false
        }
    }
}

if ($ConfigurePgpt -and $SkipPgpt) {
    throw "ConfigurePgpt and SkipPgpt cannot be used together."
}
if ($InstallCodex -and $SkipCodex) {
    throw "InstallCodex and SkipCodex cannot be used together."
}
if ($PgptNetworkCheck -and $NoNetwork) {
    throw "PgptNetworkCheck and NoNetwork cannot be used together."
}

Set-Location -LiteralPath $RepositoryRoot
Write-Host "[Lumina] Checking required tools..."
Install-UvIfMissing
Assert-Command "node" "Install the current Node.js LTS from https://nodejs.org/en/download."
Assert-Command "npm" "npm is included with Node.js; reinstall the current Node.js LTS from https://nodejs.org/en/download."
Assert-NodeVersion
Enable-UvSystemCertificates
$NpmCommand = if ($env:OS -eq "Windows_NT") {
    (Get-Command "npm.cmd" -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
}
else {
    (Get-Command "npm" -ErrorAction Stop | Select-Object -First 1).Source
}
Assert-Command "git" "Install Git from https://git-scm.com/downloads. It is required to install the National Assembly MCP server."
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
    $enablePgpt = Read-LuminaYesNoChoice `
        -Prompt "Configure the optional P-GPT provider now?"
}

$enableCodex = [bool]$InstallCodex
if (-not $InstallCodex -and -not $SkipCodex -and -not $NonInteractive) {
    $choice = Read-Host "Install the optional Codex Provider support? [y/N]"
    $enableCodex = $choice -match '^(?i)y(?:es)?$'
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
    if ($enableCodex) {
        $pythonInstallArguments += @("--extra", "codex")
    }
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
    Set-LuminaDotEnvValue -Path $EnvFile -Key "LUMINA_TLS_COMPAT_MODE" -Value "true"
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
    $tlsCompatMode = (Get-ConfiguredValue -Key "LUMINA_TLS_COMPAT_MODE") -match '^(?i:1|true|yes|on)$'
    Set-TrustEnvironment `
        -BundlePath $resolvedBundle `
        -CompanyCaPath $resolvedCa `
        -TlsCompatMode:$tlsCompatMode
}

if (-not $SkipDependencyInstall) {
    Write-Host "[Lumina] Installing frontend dependencies..."
    Assert-LuminaFrontendNativeModulesUnlocked -WebRoot $WebRoot
    $frontendInstallArguments = @("ci", "--prefix", $WebRoot)
    if ($NoNetwork) {
        $frontendInstallArguments += @("--offline", "--no-audit")
    }
    Invoke-Checked -Command $NpmCommand -Arguments $frontendInstallArguments

    Write-Host "[Lumina] Installing Korea Weather MCP dependencies..."
    $weatherInstallArguments = @("ci", "--prefix", $WeatherMcpRoot)
    if ($NoNetwork) {
        $weatherInstallArguments += @("--offline", "--no-audit")
    }
    Invoke-Checked -Command $NpmCommand -Arguments $weatherInstallArguments

    Write-Host "[Lumina] Installing the pinned National Assembly MCP server..."
    $assemblyInstallArguments = @(
        "run", "--project", $ServerRoot,
        "python", (Join-Path $RepositoryRoot "extensions/mcp/national_assembly_bootstrap.py"),
        "--install-only"
    )
    if ($NoNetwork) {
        $assemblyInstallArguments += "--offline"
    }
    Invoke-Checked -Command "uv" -Arguments $assemblyInstallArguments
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
    $runPgptNetworkCheck = Read-LuminaYesNoChoice `
        -Prompt "Run the opt-in P-GPT connection diagnostic now?"
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
