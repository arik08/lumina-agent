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

$inputFunction = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-HardResetInput"
    },
    $true
)
if ($null -eq $inputFunction) {
    throw "Test-HardResetInput was not found."
}
. ([scriptblock]::Create($inputFunction.Extent.Text))

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
$usesNativeTreeKill = $stopTreeFunction.Extent.Text -match
    '(?s)taskkill\.exe.*?/PID.*?/T.*?/F'
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
if (-not $usesNativeTreeKill -or -not $usesFastSupervisorIdentity -or -not $usesOneProcessSnapshot) {
    throw "Process cleanup must use native tree termination, a versioned supervisor identity, and one process snapshot."
}

$startupResetRestartsBoth = $source -match 
    '(?s)if \(-not \(Wait-LuminaReady\)\) \{\s*\$preserveFrontend = \$false'
$runningResetRestartsBoth = $source -match
    '(?s)if \(Test-HardResetKey\) \{\s*\$preserveFrontend = \$false\s*\$resetReason = "manual request"'
if (-not $startupResetRestartsBoth -or -not $runningResetRestartsBoth) {
    throw "Both startup and running manual reset paths must restart Frontend and Backend."
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
    if ($stopwatch.Elapsed.TotalSeconds -ge 10) {
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
if ($null -eq $startProcessesFunction -or $null -eq $prepareRuntimeFunction) {
    throw "Launcher preparation and process-start functions must both exist."
}
if (
    $null -eq $restartDelayFunction -or
    $null -eq $stateTextFunction -or
    $null -eq $errorDetailsFunction -or
    $null -eq $startupStateFunction
) {
    throw "Launcher restart and startup-state functions must all exist."
}
. ([scriptblock]::Create($restartDelayFunction.Extent.Text))
. ([scriptblock]::Create($startManagedProcessFunction.Extent.Text))
. ([scriptblock]::Create($stateTextFunction.Extent.Text))
. ([scriptblock]::Create($errorDetailsFunction.Extent.Text))
. ([scriptblock]::Create($startupStateFunction.Extent.Text))

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
$preparationCall = $source.LastIndexOf('Confirm-LuminaRuntimePrepared')
$supervisorLoop = $source.IndexOf('while ($true)', $preparationCall)
if ($preparationCall -lt 0 -or $supervisorLoop -lt 0 -or $preparationCall -ge $supervisorLoop) {
    throw "Runtime preparation must happen before the automatic supervisor loop."
}
if (
    $source -match '\$MaxAutomaticRestarts' -or
    $source -match 'RESTART_EXHAUSTED' -or
    $source -match 'exhausted its automatic restart budget'
) {
    throw "The supervisor must stay alive and keep retrying until explicitly stopped."
}
if ($source -notmatch '\$StartupTimeoutSeconds\s*=\s*90') {
    throw "The startup deadline must allow a 90-second Windows cold start."
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

$foreignPort = Get-LuminaLauncherErrorDetails `
    -Phase "STARTING_PROCESSES" `
    -Message "Port 5253 is used by a non-Lumina process: sample.exe (PID 10)"
if ($foreignPort.Code -ne "PORT_IN_USE_FOREIGN") {
    throw "Foreign port ownership must have a stable launcher error code."
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

Write-Host "run_lumina tests passed ($($cases.Count) key cases, persistent self-healing restart policy, atomic startup diagnostics, preparation isolation, and identity-safe process cleanup)."
