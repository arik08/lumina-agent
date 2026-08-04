$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "run_lumina.ps1"
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -gt 0) {
    throw "run_lumina.ps1 has parser errors: $($errors.Message -join '; ')"
}

$stopScriptPath = Join-Path $PSScriptRoot "stop_lumina.ps1"
$stopTokens = $null
$stopErrors = $null
$stopAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $stopScriptPath,
    [ref]$stopTokens,
    [ref]$stopErrors
)
if ($stopErrors.Count -gt 0) {
    throw "stop_lumina.ps1 has parser errors: $($stopErrors.Message -join '; ')"
}
$stopIdentityFunction = $stopAst.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-LuminaSupervisorIdentity"
    },
    $true
)
if ($null -eq $stopIdentityFunction) {
    throw "Get-LuminaSupervisorIdentity was not found."
}
. ([scriptblock]::Create($stopIdentityFunction.Extent.Text))

$inputSourcePath = Join-Path $PSScriptRoot "LuminaLauncher.Input.ps1"
$inputTokens = $null
$inputErrors = $null
$inputAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $inputSourcePath,
    [ref]$inputTokens,
    [ref]$inputErrors
)
if ($inputErrors.Count -gt 0) {
    throw "LuminaLauncher.Input.ps1 has parser errors: $($inputErrors.Message -join '; ')"
}
$inputFunctions = $inputAst.FindAll(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -in @("Test-HardResetInput", "Test-LuminaExitInput")
    },
    $true
)
if ($inputFunctions.Count -ne 2) {
    throw "Lumina launcher input functions were not found."
}
foreach ($inputFunction in $inputFunctions) {
    . ([scriptblock]::Create($inputFunction.Extent.Text))
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$developmentLauncherPath = Join-Path $repositoryRoot "run_lumina_dev.bat"
$developmentLauncherSource = Get-Content -Raw -LiteralPath $developmentLauncherPath
$restartPromptPath = Join-Path $PSScriptRoot "Wait-LuminaLauncherRestart.ps1"
$restartPromptSource = Get-Content -Raw -LiteralPath $restartPromptPath
$alreadyRunningBranch = [regex]::Match(
    $developmentLauncherSource,
    '(?s)if "%LUMINA_DEV_EXIT%"=="76" \(.*?\)'
)
$databaseOwnershipBranch = [regex]::Match(
    $developmentLauncherSource,
    '(?s)if "%LUMINA_DEV_EXIT%"=="77" \(.*?exit /b %LUMINA_DEV_EXIT%.*?\)'
)
if (
    $developmentLauncherSource -notmatch '(?m)^:run_lumina\s*$' -or
    $developmentLauncherSource -notmatch 'Wait-LuminaLauncherRestart\.ps1' -or
    $developmentLauncherSource -notmatch 'if "%ERRORLEVEL%"=="75"' -or
    $developmentLauncherSource -notmatch 'goto run_lumina' -or
    $restartPromptSource -notmatch 'LuminaLauncher\.Input\.ps1' -or
    $restartPromptSource -notmatch 'Test-HardResetInput' -or
    $restartPromptSource -notmatch 'exit 75' -or
    -not $alreadyRunningBranch.Success -or
    $alreadyRunningBranch.Value -match 'exit /b' -or
    -not $databaseOwnershipBranch.Success -or
    $alreadyRunningBranch.Index -gt $developmentLauncherSource.IndexOf('Wait-LuminaLauncherRestart.ps1') -or
    $databaseOwnershipBranch.Index -gt $developmentLauncherSource.IndexOf('Wait-LuminaLauncherRestart.ps1')
) {
    throw "The development launcher must keep port-conflict details visible and avoid retrying database ownership conflicts."
}

$takeoverFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Enter-LuminaPortLocksWithTakeover"
    },
    $true
)
if (
    $null -eq $takeoverFunction -or
    $takeoverFunction.Extent.Text -notmatch 'Stop-PreviousSupervisor' -or
    $takeoverFunction.Extent.Text -notmatch 'Enter-LuminaPortLocks' -or
    $ast.Extent.Text -notmatch
        'if \(-not \(Enter-LuminaPortLocksWithTakeover -Ports \$claimedPorts\)\)'
) {
    throw "The launcher must safely take over a matching previous supervisor before reporting a port conflict."
}
if (
    $developmentLauncherSource -notmatch 'if "%LUMINA_DEV_EXIT%"=="78" exit /b 0' -or
    (Get-Content -Raw -LiteralPath (Join-Path $repositoryRoot "run_lumina.bat")) -notmatch
        'if "%LUMINA_EXIT%"=="78" exit /b 0'
) {
    throw "A user-requested shutdown must close both Windows launchers cleanly."
}

$startManagedProcessFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedProcess"
    },
    $true
)
if ($null -eq $startManagedProcessFunction) {
    throw "Start-ManagedProcess was not found."
}
. ([scriptblock]::Create($startManagedProcessFunction.Extent.Text))

$processMatcherFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-LuminaCommandLine"
    },
    $true
)
if ($null -eq $processMatcherFunction) {
    throw "Test-LuminaCommandLine was not found."
}
. ([scriptblock]::Create($processMatcherFunction.Extent.Text))
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$nativeTreeFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-LuminaNativeProcessTreeIds"
    },
    $true
)
$stopTreesFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Stop-ProcessTrees"
    },
    $true
)
if ($null -eq $nativeTreeFunction -or $null -eq $stopTreesFunction) {
    throw "Fast process-tree cleanup functions were not found."
}
. ([scriptblock]::Create($nativeTreeFunction.Extent.Text))
. ([scriptblock]::Create($stopTreesFunction.Extent.Text))
Stop-ProcessTrees -ProcessIds @()

$stopTreeFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Stop-ProcessTree"
    },
    $true
)
if ($null -eq $stopTreeFunction) {
    throw "Stop-ProcessTree was not found."
}
. ([scriptblock]::Create($stopTreeFunction.Extent.Text))

$stopPreviousFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Stop-PreviousSupervisor"
    },
    $true
)
if ($null -eq $stopPreviousFunction) {
    throw "Stop-PreviousSupervisor was not found."
}
. ([scriptblock]::Create($stopPreviousFunction.Extent.Text))

$enterPortLocksFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Enter-LuminaPortLocks"
    },
    $true
)
$exitPortLocksFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Exit-LuminaPortLocks"
    },
    $true
)
if ($null -eq $enterPortLocksFunction -or $null -eq $exitPortLocksFunction) {
    throw "Port ownership lock functions were not found."
}
. ([scriptblock]::Create($exitPortLocksFunction.Extent.Text))
. ([scriptblock]::Create($enterPortLocksFunction.Extent.Text))

$runtimeFileSuffixFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-LuminaRuntimeFileSuffix"
    },
    $true
)
if ($null -eq $runtimeFileSuffixFunction) {
    throw "Get-LuminaRuntimeFileSuffix was not found."
}
. ([scriptblock]::Create($runtimeFileSuffixFunction.Extent.Text))

$qaIsolationFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Set-LuminaQaIsolationEnvironment"
    },
    $true
)
$databaseOwnershipFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-LuminaDatabaseOwnershipFailure"
    },
    $true
)
if ($null -eq $qaIsolationFunction -or $null -eq $databaseOwnershipFunction) {
    throw "QA isolation and database ownership detection functions were not found."
}
. ([scriptblock]::Create($qaIsolationFunction.Extent.Text))
. ([scriptblock]::Create($databaseOwnershipFunction.Extent.Text))

$listeningPortsFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-LuminaListeningPorts"
    },
    $true
)
$lanAddressesFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-LanIPv4Addresses"
    },
    $true
)
if ($null -eq $listeningPortsFunction -or $null -eq $lanAddressesFunction) {
    throw "Fast launcher network inspection functions were not found."
}
. ([scriptblock]::Create($listeningPortsFunction.Extent.Text))
. ([scriptblock]::Create($lanAddressesFunction.Extent.Text))

$cases = @(
    @{ Name = "lowercase r"; Character = [char]'r'; VirtualKeyCode = 0; Expected = $true },
    @{ Name = "uppercase R"; Character = [char]'R'; VirtualKeyCode = 0; Expected = $true },
    @{ Name = "Korean giyeok"; Character = [char]0x3131; VirtualKeyCode = 0; Expected = $true },
    @{ Name = "IME physical R key"; Character = [char]0; VirtualKeyCode = [int][ConsoleKey]::R; Expected = $true },
    @{ Name = "unrelated key"; Character = [char]'x'; VirtualKeyCode = [int][ConsoleKey]::X; Expected = $false }
)
foreach ($case in $cases) {
    $actual = Test-HardResetInput `
        -Character $case.Character `
        -VirtualKeyCode $case.VirtualKeyCode
    if ($actual -ne $case.Expected) {
        throw "$($case.Name): expected $($case.Expected), got $actual"
    }
}

$exitCases = @(
    @{ Name = "lowercase q"; Character = [char]'q'; VirtualKeyCode = 0; Expected = $true },
    @{ Name = "uppercase Q"; Character = [char]'Q'; VirtualKeyCode = 0; Expected = $true },
    @{ Name = "Korean bieup"; Character = [char]0x3142; VirtualKeyCode = 0; Expected = $true },
    @{ Name = "IME physical Q key"; Character = [char]0; VirtualKeyCode = [int][ConsoleKey]::Q; Expected = $true },
    @{ Name = "unrelated key"; Character = [char]'x'; VirtualKeyCode = [int][ConsoleKey]::X; Expected = $false }
)
foreach ($case in $exitCases) {
    $actual = Test-LuminaExitInput `
        -Character $case.Character `
        -VirtualKeyCode $case.VirtualKeyCode
    if ($actual -ne $case.Expected) {
        throw "$($case.Name): expected $($case.Expected), got $actual"
    }
}

$runtimeFileCases = @(
    @{
        Development = $true
        FrontendPort = 5252
        BackendPort = 5253
        ExpectedSuffix = ""
        ExpectedPidFile = "run_lumina_dev.pid"
    },
    @{
        Development = $true
        FrontendPort = 15252
        BackendPort = 15253
        ExpectedSuffix = ".15252-15253"
        ExpectedPidFile = "run_lumina_dev.15252-15253.pid"
    },
    @{
        Development = $false
        FrontendPort = 5252
        BackendPort = 5253
        ExpectedSuffix = ""
        ExpectedPidFile = "run_lumina.pid"
    },
    @{
        Development = $false
        FrontendPort = 15252
        BackendPort = 15253
        ExpectedSuffix = ".15253"
        ExpectedPidFile = "run_lumina.15253.pid"
    }
)
foreach ($case in $runtimeFileCases) {
    $actualSuffix = Get-LuminaRuntimeFileSuffix `
        -IsDevelopment $case.Development `
        -FrontendPort $case.FrontendPort `
        -BackendPort $case.BackendPort
    $baseName = if ($case.Development) { "run_lumina_dev" } else { "run_lumina" }
    $actualPidFile = "$baseName$actualSuffix.pid"
    if (
        $actualSuffix -ne $case.ExpectedSuffix -or
        $actualPidFile -ne $case.ExpectedPidFile
    ) {
        throw "Runtime file isolation did not preserve default and isolated port names."
    }
}

$qaIsolationRoot = Join-Path $env:TEMP "lumina-qa-isolation-test-$([guid]::NewGuid())"
$qaEnvironmentNames = @(
    "LUMINA_FRONTEND_PORT",
    "LUMINA_BACKEND_PORT",
    "DATABASE_URL",
    "LUMINA_DATABASE_URL",
    "LUMINA_FILES_DIR",
    "LUMINA_ARTIFACTS_DIR",
    "LUMINA_LAUNCHER_DATABASE_URL",
    "LUMINA_LAUNCHER_FILES_DIR",
    "LUMINA_LAUNCHER_ARTIFACTS_DIR"
)
$originalQaEnvironment = @{}
foreach ($name in $qaEnvironmentNames) {
    $originalQaEnvironment[$name] = [Environment]::GetEnvironmentVariable(
        $name,
        "Process"
    )
}
try {
    [Environment]::SetEnvironmentVariable(
        "LUMINA_FRONTEND_PORT",
        "46252",
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "LUMINA_BACKEND_PORT",
        "46253",
        "Process"
    )
    foreach ($name in @(
        "DATABASE_URL",
        "LUMINA_DATABASE_URL",
        "LUMINA_FILES_DIR",
        "LUMINA_ARTIFACTS_DIR",
        "LUMINA_LAUNCHER_DATABASE_URL",
        "LUMINA_LAUNCHER_FILES_DIR",
        "LUMINA_LAUNCHER_ARTIFACTS_DIR"
    )) {
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    Set-LuminaQaIsolationEnvironment `
        -IsDevelopment $true `
        -FrontendPort 46252 `
        -BackendPort 46253 `
        -RepositoryRoot $qaIsolationRoot `
        -RuntimeFileSuffix ".46252-46253"
    $expectedQaRoot = Join-Path $qaIsolationRoot "data/qa-runtime/46252-46253"
    $expectedDatabasePath = (Join-Path $expectedQaRoot "database/lumina.db").Replace('\', '/')
    if (
        $env:DATABASE_URL -ne "sqlite:///$expectedDatabasePath" -or
        $env:LUMINA_FILES_DIR -ne (Join-Path $expectedQaRoot "files") -or
        $env:LUMINA_ARTIFACTS_DIR -ne (Join-Path $expectedQaRoot "artifacts") -or
        $env:LUMINA_LAUNCHER_DATABASE_URL -ne "sqlite:///$expectedDatabasePath" -or
        $env:LUMINA_LAUNCHER_FILES_DIR -ne (Join-Path $expectedQaRoot "files") -or
        $env:LUMINA_LAUNCHER_ARTIFACTS_DIR -ne (Join-Path $expectedQaRoot "artifacts")
    ) {
        throw "Process-level QA ports did not receive isolated runtime storage."
    }

    $explicitDatabaseUrl = "sqlite:///explicit-qa.db"
    [Environment]::SetEnvironmentVariable(
        "DATABASE_URL",
        $explicitDatabaseUrl,
        "Process"
    )
    Set-LuminaQaIsolationEnvironment `
        -IsDevelopment $true `
        -FrontendPort 47252 `
        -BackendPort 47253 `
        -RepositoryRoot $qaIsolationRoot `
        -RuntimeFileSuffix ".47252-47253"
    if (
        $env:DATABASE_URL -ne $explicitDatabaseUrl -or
        $env:LUMINA_LAUNCHER_DATABASE_URL -ne $explicitDatabaseUrl
    ) {
        throw "An explicit QA DATABASE_URL was overwritten by the launcher."
    }

    $ownershipLog = Join-Path $qaIsolationRoot "backend.err.log"
    New-Item -ItemType Directory -Force -Path $qaIsolationRoot | Out-Null
    [System.IO.File]::WriteAllText(
        $ownershipLog,
        "Another Lumina Backend already owns this SQLite database."
    )
    if (-not (Test-LuminaDatabaseOwnershipFailure -ErrorLog $ownershipLog)) {
        throw "SQLite database ownership failure was not detected."
    }
    [System.IO.File]::WriteAllText($ownershipLog, "Unrelated startup failure")
    if (Test-LuminaDatabaseOwnershipFailure -ErrorLog $ownershipLog) {
        throw "An unrelated Backend failure was classified as database ownership."
    }
}
finally {
    foreach ($name in $qaEnvironmentNames) {
        [Environment]::SetEnvironmentVariable(
            $name,
            $originalQaEnvironment[$name],
            "Process"
        )
    }
    Remove-Item -LiteralPath $qaIsolationRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    0
)
try {
    $listener.Start()
    $listenerPort = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    if ($listenerPort -notin @(Get-LuminaListeningPorts -Ports @($listenerPort))) {
        throw "Fast port inspection did not find an active TCP listener."
    }
}
finally {
    $listener.Stop()
}
if ($listenerPort -in @(Get-LuminaListeningPorts -Ports @($listenerPort))) {
    throw "Fast port inspection retained a stopped TCP listener."
}
$lanAddresses = @(Get-LanIPv4Addresses)
if (
    $lanAddresses.Count -ne @($lanAddresses | Sort-Object -Unique).Count -or
    @($lanAddresses | Where-Object { $_ -match '^127\.' -or $_ -match '^169\.254\.' }).Count -gt 0
) {
    throw "Fast LAN address inspection returned duplicate or local-only addresses."
}

$lockTestRoot = Join-Path $env:TEMP "lumina-port-lock-test-$([guid]::NewGuid())"
$originalLogRoot = $LogRoot
$externalLock = $null
try {
    New-Item -ItemType Directory -Path $lockTestRoot -Force | Out-Null
    $LogRoot = $lockTestRoot
    $script:LauncherPortLocks = @()
    $script:LauncherLockConflictPort = 0

    if (-not (Enter-LuminaPortLocks -Ports @(45253, 45252))) {
        throw "The first launcher could not claim free ports."
    }
    if ($script:LauncherPortLocks.Count -ne 2) {
        throw "The launcher did not retain both port ownership locks."
    }
    $claimedLockPath = Join-Path $lockTestRoot "run_lumina.port.45252.lock"
    $claimWasExclusive = $false
    try {
        $probe = [System.IO.File]::Open(
            $claimedLockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $probe.Dispose()
    }
    catch [System.IO.IOException] {
        $claimWasExclusive = $true
    }
    if (-not $claimWasExclusive) {
        throw "A claimed Lumina port lock was not exclusive."
    }
    Exit-LuminaPortLocks

    $partialLockPath = Join-Path $lockTestRoot "run_lumina.port.45255.lock"
    $externalLock = [System.IO.File]::Open(
        $partialLockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    if (Enter-LuminaPortLocks -Ports @(45254, 45255)) {
        throw "A second launcher claimed a port already owned by another launcher."
    }
    if ($script:LauncherLockConflictPort -ne 45255) {
        throw "The conflicting launcher port was not reported."
    }
    $releasedPartialPath = Join-Path $lockTestRoot "run_lumina.port.45254.lock"
    $releasedPartialLock = [System.IO.File]::Open(
        $releasedPartialPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    $releasedPartialLock.Dispose()
}
finally {
    Exit-LuminaPortLocks
    if ($null -ne $externalLock) {
        $externalLock.Dispose()
    }
    $LogRoot = $originalLogRoot
    Remove-Item -LiteralPath $lockTestRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$environmentTestRoot = Join-Path $env:TEMP "lumina-managed-env-test-$([guid]::NewGuid())"
$environmentOutputLog = Join-Path $environmentTestRoot "stdout.log"
$environmentErrorLog = Join-Path $environmentTestRoot "stderr.log"
$originalCi = [Environment]::GetEnvironmentVariable("CI", "Process")
try {
    New-Item -ItemType Directory -Path $environmentTestRoot -Force | Out-Null
    [Environment]::SetEnvironmentVariable("CI", "parent-value", "Process")
    $environmentProcess = Start-ManagedProcess `
        -Name "Environment fixture" `
        -FilePath $env:ComSpec `
        -Arguments @('/d', '/c', 'echo %CI%') `
        -WorkingDirectory $environmentTestRoot `
        -OutputLog $environmentOutputLog `
        -ErrorLog $environmentErrorLog `
        -EnvironmentVariables @{ CI = "true" }
    $environmentProcess.Process.WaitForExit()
    if ((Get-Content -Raw $environmentOutputLog).Trim() -ne "true") {
        throw "Managed child process did not inherit its isolated environment."
    }
    if ([Environment]::GetEnvironmentVariable("CI", "Process") -ne "parent-value") {
        throw "Managed child process environment leaked into the launcher."
    }
}
finally {
    [Environment]::SetEnvironmentVariable("CI", $originalCi, "Process")
    Get-ChildItem -LiteralPath $environmentTestRoot -File -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $environmentTestRoot -Force -ErrorAction SilentlyContinue
}

$supervisorScript = Join-Path $RepositoryRoot "devtools\run_lumina.ps1"
$viteScript = Join-Path $RepositoryRoot "apps\web\node_modules\vite\bin\vite.js"
if (-not (Test-LuminaCommandLine -ProcessName "powershell.exe" -CommandLine "powershell -File `"$supervisorScript`"")) {
    throw "The Lumina PowerShell supervisor was not recognized."
}
if (-not (Test-LuminaCommandLine -ProcessName "python.exe" -CommandLine "python -m uvicorn lumina.main:app")) {
    throw "The Lumina backend was not recognized."
}
if (-not (Test-LuminaCommandLine -ProcessName "node.exe" -CommandLine "node `"$viteScript`"")) {
    throw "The Lumina Vite frontend was not recognized."
}
$batchWrapper = "cmd.exe /c `"$RepositoryRoot\run_lumina_dev.bat`""
if (Test-LuminaCommandLine -ProcessName "cmd.exe" -CommandLine $batchWrapper) {
    throw "The batch wrapper must not be treated as a managed Lumina process root."
}

$source = [System.IO.File]::ReadAllText($scriptPath)
$stopManagedProcessesFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Stop-ManagedProcesses"
    },
    $true
)
$usesNativeTreeKill = (
    $nativeTreeFunction.Extent.Text -match 'CreateToolhelp32Snapshot' -and
    $nativeTreeFunction.Extent.Text -notmatch 'Get-CimInstance' -and
    $stopTreesFunction.Extent.Text -match 'Get-LuminaNativeProcessTreeIds' -and
    $stopTreesFunction.Extent.Text -match 'taskkill\.exe' -and
    $stopTreesFunction.Extent.Text.IndexOf('Get-LuminaNativeProcessTreeIds') -lt
        $stopTreesFunction.Extent.Text.IndexOf('taskkill.exe') -and
    $null -ne $stopManagedProcessesFunction -and
    $stopManagedProcessesFunction.Extent.Text -match
        'Stop-ProcessTrees\s+-ProcessIds\s+\$processIds'
)
$waitReadyFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Wait-LuminaReady"
    },
    $true
)
$warmsNativeSnapshotDuringProgress = (
    $null -ne $waitReadyFunction -and
    $waitReadyFunction.Extent.Text -match
        '(?s)Write-LuminaStartupProgress.*?Get-LuminaNativeProcessTreeIds'
)
$usesFastSupervisorIdentity = $source -match
    '(?s)function Set-SupervisorPid.*?StartTime\.ToUniversalTime\(\)\.Ticks' -and
    $source -match '(?s)function Stop-PreviousSupervisor.*?-split ''\\\|'', 2'
$rootLookupFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-LuminaProcessRootId"
    },
    $true
)
$usesOneProcessSnapshot = (
    $null -ne $rootLookupFunction -and
    $rootLookupFunction.Extent.Text -match 'ProcessesById' -and
    $rootLookupFunction.Extent.Text -notmatch 'Get-CimInstance'
)
if (
    -not $usesNativeTreeKill -or
    -not $warmsNativeSnapshotDuringProgress -or
    -not $usesFastSupervisorIdentity -or
    -not $usesOneProcessSnapshot
) {
    throw "Process cleanup must use the fast native tree snapshot before fallback, a versioned supervisor identity, and one listener snapshot."
}

$startupResetRestartsBoth = $source -match
    '(?s)if \(\$startupAction -eq "restart"\) \{\s*Write-Host "\[Lumina\] Restart requested\..*?"\s*\$preserveFrontend = \$false'
$runningResetRestartsBoth = $source -match
    '(?s)if \(\$controlAction -eq "restart"\) \{\s*Write-Host "\[Lumina\] Restart requested\..*?"\s*\$preserveFrontend = \$false\s*\$resetReason = "manual request"'
if (-not $startupResetRestartsBoth -or -not $runningResetRestartsBoth) {
    throw "Both startup and running manual reset paths must restart Frontend and Backend."
}
$startupExitStopsBoth = $source -match
    '(?s)if \(\$startupAction -eq "exit"\) \{\s*Write-Host "\[Lumina\] Stop requested\..*?"\s*\$preserveFrontend = \$false\s*\$userExitRequested = \$true'
$runningExitStopsBoth = $source -match
    '(?s)if \(\$controlAction -eq "exit"\) \{\s*Write-Host "\[Lumina\] Stop requested\..*?"\s*\$preserveFrontend = \$false\s*\$userExitRequested = \$true'
$exitUsesFinalCleanup = $source -match
    '(?s)finally \{\s*(?:Clear-LuminaStartupProgress\s*)?Stop-ManagedProcesses\s*Remove-SupervisorPid\s*Exit-LuminaPortLocks.*?if \(\$userExitRequested\) \{\s*exit \$UserRequestedExitCode'
if (-not $startupExitStopsBoth -or -not $runningExitStopsBoth -or -not $exitUsesFinalCleanup) {
    throw "All user-requested shutdown paths must clean up every managed process before exiting."
}

$startLuminaProcessesFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-LuminaProcesses"
    },
    $true
)
if (
    $null -eq $startLuminaProcessesFunction -or
    $startLuminaProcessesFunction.Extent.Text -notmatch '(?s)-Name "Frontend".*-EnvironmentVariables\s+@\{\s*CI\s*=\s*"true"\s*\}'
) {
    throw "Vite must not inherit the launcher console input or consume the hard-reset key."
}

$treeParent = $null
$treeChildId = 0
try {
    $treeParent = Start-Process `
        -FilePath $env:ComSpec `
        -ArgumentList @('/d', '/c', 'ping.exe 127.0.0.1 -t > nul') `
        -WindowStyle Hidden `
        -PassThru
    $childDeadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $childDeadline -and $treeChildId -le 0) {
        $child = Get-CimInstance `
            Win32_Process `
            -Filter "ParentProcessId = $($treeParent.Id)" `
            -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $child) {
            $treeChildId = [int]$child.ProcessId
            break
        }
        Start-Sleep -Milliseconds 50
    }
    if ($treeChildId -le 0) {
        throw "The process-tree fixture did not create a child process."
    }

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    Stop-ProcessTree -ProcessId $treeParent.Id
    $stopwatch.Stop()
    if ($null -ne (Get-Process -Id $treeParent.Id -ErrorAction SilentlyContinue)) {
        throw "Stop-ProcessTree left the test parent process running."
    }
    if ($null -ne (Get-Process -Id $treeChildId -ErrorAction SilentlyContinue)) {
        throw "Stop-ProcessTree left the test child process running."
    }
    if ($stopwatch.Elapsed.TotalSeconds -ge 5) {
        throw "Stop-ProcessTree took $([math]::Round($stopwatch.Elapsed.TotalSeconds, 2)) seconds."
    }
}
finally {
    if ($treeChildId -gt 0) {
        Stop-Process -Id $treeChildId -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $treeParent) {
        Stop-Process -Id $treeParent.Id -Force -ErrorAction SilentlyContinue
    }
}

$managedFixtureProcesses = @()
try {
    foreach ($index in 1..2) {
        $managedFixtureProcesses += Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 60') `
            -WindowStyle Hidden `
            -PassThru
    }
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    Stop-ProcessTrees -ProcessIds $managedFixtureProcesses.Id
    $stopwatch.Stop()
    if (
        @(
            $managedFixtureProcesses |
                Where-Object { Get-Process -Id $_.Id -ErrorAction SilentlyContinue }
        ).Count -gt 0
    ) {
        throw "Stop-ProcessTrees left a managed process running."
    }
    if ($stopwatch.Elapsed.TotalSeconds -ge 3) {
        throw "Batched managed cleanup took $([math]::Round($stopwatch.Elapsed.TotalSeconds, 2)) seconds."
    }
}
finally {
    foreach ($process in $managedFixtureProcesses) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
}

$SupervisorPidPath = Join-Path $env:TEMP "lumina-supervisor-test-$([guid]::NewGuid()).pid"
$matchingSupervisor = $null
$mismatchedSupervisor = $null
try {
    $matchingSupervisor = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 30') `
        -WindowStyle Hidden `
        -PassThru
    $matchingIdentity = (
        "$($matchingSupervisor.Id)|" +
        "$($matchingSupervisor.StartTime.ToUniversalTime().Ticks)"
    )
    [System.IO.File]::WriteAllText($SupervisorPidPath, $matchingIdentity)
    Stop-PreviousSupervisor
    if ($null -ne (Get-Process -Id $matchingSupervisor.Id -ErrorAction SilentlyContinue)) {
        throw "A supervisor with a matching process identity was not stopped."
    }

    $mismatchedSupervisor = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 30') `
        -WindowStyle Hidden `
        -PassThru
    $mismatchedIdentity = "$($mismatchedSupervisor.Id)|1"
    [System.IO.File]::WriteAllText($SupervisorPidPath, $mismatchedIdentity)
    Stop-PreviousSupervisor
    if ($null -eq (Get-Process -Id $mismatchedSupervisor.Id -ErrorAction SilentlyContinue)) {
        throw "A supervisor with a mismatched process identity was stopped."
    }
}
finally {
    if ($null -ne $matchingSupervisor) {
        Stop-Process -Id $matchingSupervisor.Id -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $mismatchedSupervisor) {
        Stop-Process -Id $mismatchedSupervisor.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $SupervisorPidPath -Force -ErrorAction SilentlyContinue
}

$stopSupervisorPidPath = Join-Path `
    $env:TEMP `
    "lumina-stop-supervisor-test-$([guid]::NewGuid()).pid"
$stopSupervisor = $null
try {
    $stopSupervisor = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 30') `
        -WindowStyle Hidden `
        -PassThru
    $stopIdentity = (
        "$($stopSupervisor.Id)|" +
        "$($stopSupervisor.StartTime.ToUniversalTime().Ticks)"
    )
    [System.IO.File]::WriteAllText($stopSupervisorPidPath, $stopIdentity)
    $resolvedStopIdentity = Get-LuminaSupervisorIdentity `
        -PidPath $stopSupervisorPidPath
    if (
        $null -eq $resolvedStopIdentity -or
        $resolvedStopIdentity.ProcessId -ne $stopSupervisor.Id
    ) {
        throw "The stop launcher did not resolve a matching supervisor identity."
    }

    [System.IO.File]::WriteAllText(
        $stopSupervisorPidPath,
        "$($stopSupervisor.Id)|1"
    )
    if ($null -ne (Get-LuminaSupervisorIdentity -PidPath $stopSupervisorPidPath)) {
        throw "The stop launcher accepted a reused or mismatched supervisor identity."
    }
}
finally {
    if ($null -ne $stopSupervisor) {
        Stop-Process -Id $stopSupervisor.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item `
        -LiteralPath $stopSupervisorPidPath `
        -Force `
        -ErrorAction SilentlyContinue
}

$startProcessesFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-LuminaProcesses"
    },
    $true
)
$startManagedProcessFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedProcess"
    },
    $true
)
$prepareRuntimeFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Confirm-LuminaRuntimePrepared"
    },
    $true
)
$progressTextFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-LuminaStartupProgressText"
    },
    $true
)
$invokeCheckedFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-Checked"
    },
    $true
)
$restartDelayFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-AutomaticRestartDelay"
    },
    $true
)
$stateTextFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "ConvertTo-LuminaStateText"
    },
    $true
)
$errorDetailsFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-LuminaLauncherErrorDetails"
    },
    $true
)
$startupStateFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Write-LuminaStartupState"
    },
    $true
)
$monitoringEventFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Write-LuminaMonitoringEvent"
    },
    $true
)
if (
    $null -eq $startProcessesFunction -or
    $null -eq $prepareRuntimeFunction -or
    $null -eq $progressTextFunction -or
    $null -eq $invokeCheckedFunction
) {
    throw "Launcher preparation and process-start functions must both exist."
}
if (
    $null -eq $restartDelayFunction -or
    $null -eq $stateTextFunction -or
    $null -eq $errorDetailsFunction -or
    $null -eq $startupStateFunction -or
    $null -eq $monitoringEventFunction
) {
    throw "Launcher restart, monitoring-event, and startup-state functions must all exist."
}
. ([scriptblock]::Create($restartDelayFunction.Extent.Text))
. ([scriptblock]::Create($startManagedProcessFunction.Extent.Text))
. ([scriptblock]::Create($stateTextFunction.Extent.Text))
. ([scriptblock]::Create($errorDetailsFunction.Extent.Text))
. ([scriptblock]::Create($startupStateFunction.Extent.Text))
. ([scriptblock]::Create($monitoringEventFunction.Extent.Text))
. ([scriptblock]::Create($progressTextFunction.Extent.Text))
. ([scriptblock]::Create($invokeCheckedFunction.Extent.Text))

$expectedProgress = @(
    (([string][char]0x25A0) + (([string][char]0x25A1) * 19)),
    (([string][char]0x25A0) * 20),
    (([string][char]0x25A0) + (([string][char]0x25A1) * 19))
)
$actualProgress = @(
    (Get-LuminaStartupProgressText -Step 1),
    (Get-LuminaStartupProgressText -Step 20),
    (Get-LuminaStartupProgressText -Step 21)
)
if (($actualProgress -join '|') -ne ($expectedProgress -join '|')) {
    throw "Startup progress must fill twenty cells and then begin again."
}

function Write-LuminaStartupProgress {}
$quietCommandLogRoot = Join-Path $env:TEMP "lumina-quiet-command-$([guid]::NewGuid())"
try {
    New-Item -ItemType Directory -Force -Path $quietCommandLogRoot | Out-Null
    $quietOutputLog = Join-Path $quietCommandLogRoot "fixture.out.log"
    $quietErrorLog = Join-Path $quietCommandLogRoot "fixture.err.log"
    Invoke-Checked `
        -Command "cmd.exe" `
        -Arguments @("/d", "/c", "exit 0") `
        -OutputLog $quietOutputLog `
        -ErrorLog $quietErrorLog
    $failureMessage = ""
    try {
        Invoke-Checked `
            -Command "cmd.exe" `
            -Arguments @("/d", "/c", "exit 7") `
            -OutputLog $quietOutputLog `
            -ErrorLog $quietErrorLog
    }
    catch {
        $failureMessage = $_.Exception.Message
    }
    if ($failureMessage -notmatch 'exit code 7' -or $failureMessage -notmatch 'fixture\.err\.log') {
        throw "Quiet startup commands must preserve their exit code and error-log path."
    }
}
finally {
    Remove-Item -LiteralPath $quietCommandLogRoot -Recurse -Force -ErrorAction SilentlyContinue
}

if ($startProcessesFunction.Extent.Text -match 'alembic|npm') {
    throw "Automatic process restart must not run migration or Frontend build commands."
}
if ($startProcessesFunction.Extent.Text -match '--reload') {
    throw "Development must keep the Backend stable during Agent Runs; use explicit R restart instead of Uvicorn reload."
}
if (
    $null -eq $startManagedProcessFunction -or
    $startManagedProcessFunction.Extent.Text -notmatch 'previous\.log' -or
    $startManagedProcessFunction.Extent.Text -notmatch 'Move-Item'
) {
    throw "Automatic restarts must preserve the previous process logs for crash diagnosis."
}
$preparationSource = $prepareRuntimeFunction.Extent.Text
if (
    $preparationSource -notmatch 'current' -or
    $preparationSource -notmatch '--check-heads' -or
    $preparationSource -notmatch 'dist.*index\.html' -or
    $preparationSource -notmatch 'upgrade.*head'
) {
    throw "Runtime preparation must migrate development once and only validate production assets/schema."
}
if (
    $preparationSource -notmatch 'PreparationOutputLog' -or
    $preparationSource -notmatch 'PreparationErrorLog' -or
    $source -match 'Applying development database migrations once' -or
    $source -match '\[Lumina\] Hard reset:' -or
    $source -match 'Stopping previous Lumina process tree' -or
    $source -match 'Replacing the previous supervisor' -or
    $source -match '\[Lumina\] Logs: \$LogRoot\s*\r?\n\s*\$healthFailures'
) {
    throw "Normal startup must stay quiet while failures retain log guidance."
}
$initialStartup = $source.IndexOf('$resetReason = "initial startup"')
$preparationCall = $source.LastIndexOf(
    'Confirm-LuminaRuntimePrepared',
    $initialStartup
)
$supervisorLoop = $source.IndexOf('while ($true)', $preparationCall)
if (
    $initialStartup -lt 0 -or
    $preparationCall -lt 0 -or
    $supervisorLoop -lt 0 -or
    $preparationCall -ge $supervisorLoop
) {
    throw "Runtime preparation must happen before the automatic supervisor loop."
}
$manualResetBlock = $source.Substring(
    $source.LastIndexOf('if ($manualResetRequested)'),
    $source.LastIndexOf('if (Test-LuminaDatabaseOwnershipFailure') -
        $source.LastIndexOf('if ($manualResetRequested)')
)
if (
    $manualResetBlock -notmatch '\$runtimePreparationRequired\s*=\s*\$true' -or
    $source.Substring($supervisorLoop) -notmatch '(?s)if \(\$runtimePreparationRequired\).*?Confirm-LuminaRuntimePrepared.*?\$runtimePreparationRequired\s*=\s*\$false'
) {
    throw "Manual restart must prepare the runtime again before starting updated Backend code."
}
if (
    $source -match '\$MaxAutomaticRestarts' -or
    $source -match 'RESTART_EXHAUSTED' -or
    $source -match 'exhausted its automatic restart budget'
) {
    throw "The supervisor must stay alive and keep retrying until explicitly stopped."
}
if (
    $source -notmatch 'Write-LuminaMonitoringEvent\s+-Event\s+"manual_restart"' -or
    $source -notmatch '-Event\s+"automatic_recovery"'
) {
    throw "Manual resets and automatic recoveries must be written as distinct monitoring events."
}
$databaseOwnershipStop = $source.LastIndexOf(
    'if (Test-LuminaDatabaseOwnershipFailure'
)
$automaticRecoveryIncrement = $source.LastIndexOf('$automaticRestartCount++')
if (
    $databaseOwnershipStop -lt 0 -or
    $automaticRecoveryIncrement -lt 0 -or
    $databaseOwnershipStop -gt $automaticRecoveryIncrement
) {
    throw "SQLite ownership conflicts must stop before the automatic restart loop."
}
if ($source -notmatch '\$StartupTimeoutSeconds\s*=\s*90') {
    throw "The startup deadline must allow a 90-second Windows cold start."
}
if (
    $source -notmatch '\$StartupPollIntervalMilliseconds\s*=\s*200' -or
    $waitReadyFunction.Extent.Text -notmatch
        'Start-Sleep\s+-Milliseconds\s+\$StartupPollIntervalMilliseconds'
) {
    throw "Startup readiness must use the bounded fast polling interval."
}
if ($source -match 'Restarting in 1 second') {
    throw "The launcher must not retain the unbounded fixed one-second restart loop."
}
$expectedDelays = @(1, 2, 5, 10, 30, 30)
for ($attempt = 1; $attempt -le $expectedDelays.Count; $attempt++) {
    $actualDelay = Get-AutomaticRestartDelay -Attempt $attempt
    if ($actualDelay -ne $expectedDelays[$attempt - 1]) {
        throw "Restart attempt $attempt expected delay $($expectedDelays[$attempt - 1]), got $actualDelay."
    }
}

$processLogRoot = Join-Path $env:TEMP "lumina-process-log-test-$([guid]::NewGuid())"
$processOutputLog = Join-Path $processLogRoot "fixture.out.log"
$processErrorLog = Join-Path $processLogRoot "fixture.err.log"
try {
    New-Item -ItemType Directory -Force -Path $processLogRoot | Out-Null
    [System.IO.File]::WriteAllText($processOutputLog, "previous-out")
    [System.IO.File]::WriteAllText($processErrorLog, "previous-err")
    $encodedCommand = [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes(
            "Write-Output 'current-out'; [Console]::Error.WriteLine('current-err')"
        )
    )
    $managedProcess = Start-ManagedProcess `
        -Name "Fixture" `
        -FilePath "powershell.exe" `
        -Arguments @("-NoProfile", "-EncodedCommand", $encodedCommand) `
        -WorkingDirectory $processLogRoot `
        -OutputLog $processOutputLog `
        -ErrorLog $processErrorLog
    $managedProcess.Process.WaitForExit()
    $previousOutputLog = [System.IO.Path]::ChangeExtension(
        $processOutputLog,
        ".previous.log"
    )
    $previousErrorLog = [System.IO.Path]::ChangeExtension(
        $processErrorLog,
        ".previous.log"
    )
    if (
        [System.IO.File]::ReadAllText($previousOutputLog) -ne "previous-out" -or
        [System.IO.File]::ReadAllText($previousErrorLog) -ne "previous-err" -or
        [System.IO.File]::ReadAllText($processOutputLog) -notmatch "current-out" -or
        [System.IO.File]::ReadAllText($processErrorLog) -notmatch "current-err"
    ) {
        throw "Managed process restart did not preserve previous and current logs."
    }
}
finally {
    Remove-Item -LiteralPath $processLogRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$LauncherEventLogPath = Join-Path $env:TEMP "lumina-launcher-events-test-$([guid]::NewGuid()).jsonl"
$Development = $false
try {
    Write-LuminaMonitoringEvent -Event "automatic_recovery" -Attempt 2
    Write-LuminaMonitoringEvent -Event "manual_restart" -Attempt 3
    $monitoringEvents = @(
        Get-Content -LiteralPath $LauncherEventLogPath -Encoding utf8 |
            ForEach-Object { $_ | ConvertFrom-Json }
    )
    if (
        $monitoringEvents.Count -ne 2 -or
        $monitoringEvents[0].event -ne "automatic_recovery" -or
        $monitoringEvents[1].event -ne "manual_restart" -or
        $monitoringEvents[0].mode -ne "production" -or
        $monitoringEvents[1].attempt -ne 3
    ) {
        throw "Launcher monitoring events did not preserve type, mode, and attempt."
    }
}
finally {
    Remove-Item -LiteralPath $LauncherEventLogPath -Force -ErrorAction SilentlyContinue
}

$foreignPort = Get-LuminaLauncherErrorDetails `
    -Phase "STARTING_PROCESSES" `
    -Message "Port 5253 is used by a non-Lumina process: sample.exe (PID 10)"
if ($foreignPort.Code -ne "PORT_IN_USE_FOREIGN") {
    throw "Foreign port ownership must have a stable launcher error code."
}
$databaseOwned = Get-LuminaLauncherErrorDetails `
    -Phase "WAITING_FOR_READINESS" `
    -Message "Another Lumina Backend already owns this SQLite database."
if ($databaseOwned.Code -ne "DATABASE_ALREADY_OWNED") {
    throw "SQLite ownership conflicts must stop with a stable launcher error code."
}
$schemaMismatch = Get-LuminaLauncherErrorDetails `
    -Phase "PREFLIGHT" `
    -Message "Command failed: alembic current --check-heads"
if ($schemaMismatch.Code -ne "UPDATE_REQUIRED") {
    throw "A stale database schema must be classified as UPDATE_REQUIRED."
}
$startupTimeout = Get-LuminaLauncherErrorDetails `
    -Phase "WAITING_FOR_READINESS" `
    -Message "Lumina did not become healthy within 90 seconds."
if ($startupTimeout.Code -ne "STARTUP_TIMEOUT") {
    throw "A readiness deadline must be classified as STARTUP_TIMEOUT."
}

$stateRoot = Join-Path $env:TEMP "lumina-startup-state-test-$([guid]::NewGuid())"
$StartupStatePath = Join-Path $stateRoot "run_lumina.state.json"
$Development = $false
$script:LauncherStartedAt = [DateTime]::UtcNow.AddSeconds(-1)
$script:StartupStateSequence = 0
$script:StartupStateStatus = "starting"
try {
    Write-LuminaStartupState `
        -Status "starting" `
        -Phase "PREFLIGHT" `
        -Attempt 0
    Write-LuminaStartupState `
        -Status "restarting" `
        -Phase "WAITING_FOR_READINESS" `
        -Attempt 2 `
        -ErrorCode "STARTUP_TIMEOUT" `
        -HelpAction "Inspect data/logs." `
        -LastError "Authorization: Bearer secret-token PGPT_API_KEY=secret-key"

    $state = Get-Content -Raw -LiteralPath $StartupStatePath | ConvertFrom-Json
    if (
        $state.schemaVersion -ne 1 -or
        $state.status -ne "restarting" -or
        $state.phase -ne "WAITING_FOR_READINESS" -or
        $state.attempt -ne 2 -or
        $state.sequence -ne 2 -or
        $state.errorCode -ne "STARTUP_TIMEOUT" -or
        $state.elapsedMs -lt 900
    ) {
        throw "The atomic launcher state did not preserve its required contract."
    }
    if ($state.lastError -match 'secret-token|secret-key') {
        throw "The launcher startup state exposed a secret-like value."
    }
    if (Get-ChildItem -LiteralPath $stateRoot -Filter '*.tmp' -File) {
        throw "Atomic startup-state writes left a temporary file behind."
    }
    if (Get-ChildItem -LiteralPath $stateRoot -Filter '*.bak' -File) {
        throw "Atomic startup-state writes left a backup file behind."
    }
}
finally {
    Get-ChildItem -LiteralPath $stateRoot -File -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stateRoot -Force -ErrorAction SilentlyContinue
}

Write-Host "run_lumina tests passed ($($cases.Count) restart key cases, $($exitCases.Count) exit key cases, persistent self-healing restart policy, atomic startup diagnostics, preparation isolation, and identity-safe process cleanup)."
