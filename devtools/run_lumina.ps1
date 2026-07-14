[CmdletBinding()]
param(
    [switch]$Development
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ServerRoot = Join-Path $RepositoryRoot "apps/server"
$WebRoot = Join-Path $RepositoryRoot "apps/web"
$LogRoot = Join-Path $RepositoryRoot "data/logs"
$BackendOutputLog = Join-Path $LogRoot "backend.out.log"
$StartupStatePath = Join-Path $LogRoot $(
    if ($Development) { "run_lumina_dev.state.json" } else { "run_lumina.state.json" }
)
$script:LauncherStartedAt = [DateTime]::UtcNow
$script:StartupStateSequence = 0
$script:StartupStateStatus = "starting"
. (Join-Path $PSScriptRoot "LuminaCache.Env.ps1") -RepositoryRoot $RepositoryRoot

function Get-ConfiguredPort {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Default
    )

    $portText = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($portText)) {
        $portText = $portText.Trim()
    }
    else {
        $portText = $null
    }
    $EnvPath = Join-Path $RepositoryRoot ".env"
    if ($null -eq $portText -and (Test-Path -LiteralPath $EnvPath)) {
        $portLine = @(
            [System.IO.File]::ReadAllLines($EnvPath) |
                Where-Object { $_ -match "^\s*$Name\s*=" }
        ) | Select-Object -Last 1
        if ($null -ne $portLine) {
            $portText = ($portLine -split '=', 2)[1].Trim().Trim('"').Trim("'")
        }
    }
    if ([string]::IsNullOrWhiteSpace($portText)) {
        $portText = [string]$Default
    }
    $port = 0
    if (
        -not [int]::TryParse($portText, [ref]$port) -or
        $port -lt 1 -or
        $port -gt 65535
    ) {
        throw "$Name must be an integer between 1 and 65535. Current value: $portText"
    }
    return $port
}

$FrontendPort = Get-ConfiguredPort -Name "LUMINA_FRONTEND_PORT" -Default 5252
$BackendPort = Get-ConfiguredPort -Name "LUMINA_BACKEND_PORT" -Default 5253
if ($FrontendPort -eq $BackendPort) {
    throw "LUMINA_FRONTEND_PORT and LUMINA_BACKEND_PORT must use different ports."
}
$HealthCheckIntervalSeconds = 5
$HealthFailureThreshold = 3
$StartupTimeoutSeconds = 90
$MaxAutomaticRestarts = 3
$RestartBudgetResetSeconds = 600
$SupervisorPidPath = Join-Path $LogRoot $(
    if ($Development) { "run_lumina_dev.pid" } else { "run_lumina.pid" }
)
$script:ManagedProcesses = @()
$script:BackendActivityLineCount = 0

function Write-LuminaBanner {
    $template = @(
        '  ##R      ##R   ##R ###R   ###R ##R ###R   ##R  #####R',
        '  ##V      ##V   ##V ####R ####V ##V ####R  ##V ##LEE##R',
        '  ##V      ##V   ##V ##L####L##V ##V ##L##R ##V #######V',
        '  ##V      ##V   ##V ##VC##LJ##V ##V ##VC##R##V ##LEE##V',
        '  #######R C######LJ ##V CEJ ##V ##V ##V C####V ##V  ##V',
        '  CEEEEEEJ  CEEEEEJ  CEJ     CEJ CEJ CEJ  CEEEJ CEJ  CEJ'
    )
    $characters = @{
        '#' = [char]0x2588
        'R' = [char]0x2557
        'V' = [char]0x2551
        'L' = [char]0x2554
        'E' = [char]0x2550
        'J' = [char]0x255D
        'C' = [char]0x255A
    }
    $colors = @('Blue', 'Blue', 'Blue', 'Blue', 'Blue', 'DarkBlue')

    Write-Host ""
    for ($index = 0; $index -lt $template.Count; $index++) {
        $line = $template[$index]
        foreach ($key in $characters.Keys) {
            $line = $line.Replace($key, [string]$characters[$key])
        }
        Write-Host $line -ForegroundColor $colors[$index]
    }
    Write-Host ""
    $sparkle = [char]0x2726
    Write-Host "$sparkle Language Understanding Meets Intelligent Navigation & Automation. $sparkle" -ForegroundColor Blue
    Write-Host ""
}

function ConvertTo-LuminaStateText {
    param([AllowNull()][string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $null
    }
    $safeText = ($Text -replace '[\r\n]+', ' ').Trim()
    $safeText = $safeText -replace (
        '(?i)(authorization\s*:\s*bearer)\s+[^\s,;]+'
    ), '$1 <redacted>'
    $safeText = $safeText -replace (
        '(?i)\b[a-z0-9_]*(api[_-]?key|token|password|employee[_-]?no)\b(\s*[:=]\s*)[^\s,;]+'
    ), '$1$2<redacted>'
    if ($safeText.Length -gt 600) {
        return $safeText.Substring(0, 600)
    }
    return $safeText
}

function Get-LuminaLauncherErrorDetails {
    param(
        [Parameter(Mandatory = $true)][string]$Phase,
        [AllowNull()][string]$Message
    )

    $text = if ($null -eq $Message) { "" } else { $Message }
    if ($text -match 'used by a non-Lumina process') {
        return [pscustomobject]@{
            Code = "PORT_IN_USE_FOREIGN"
            HelpAction = "Stop the listed process or configure another Lumina port."
        }
    }
    if ($text -match 'Frontend build is missing') {
        return [pscustomobject]@{
            Code = "INSTALL_INCOMPLETE"
            HelpAction = "Run installer.bat, then start Lumina again."
        }
    }
    if ($Phase -eq "PREFLIGHT" -and $text -match 'alembic.*current.*--check-heads') {
        return [pscustomobject]@{
            Code = "UPDATE_REQUIRED"
            HelpAction = "Run installer.bat to update the database schema."
        }
    }
    if ($text -match 'exited during startup|exited unexpectedly') {
        return [pscustomobject]@{
            Code = "CHILD_EXITED"
            HelpAction = "Inspect data/logs/backend.err.log and frontend.err.log."
        }
    }
    if ($text -match 'did not become healthy') {
        return [pscustomobject]@{
            Code = "STARTUP_TIMEOUT"
            HelpAction = "Inspect the startup state and Backend error log before retrying."
        }
    }
    if ($text -match 'health check failed') {
        return [pscustomobject]@{
            Code = "HEALTH_CHECK_FAILED"
            HelpAction = "Inspect /api/health/startup and data/logs/backend.err.log."
        }
    }
    return [pscustomobject]@{
        Code = "STARTUP_FAILED"
        HelpAction = "Inspect the startup state and logs in data/logs."
    }
}

function Write-LuminaStartupState {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][string]$Phase,
        [int]$Attempt = 0,
        [AllowNull()][string]$ErrorCode = $null,
        [AllowNull()][string]$HelpAction = $null,
        [AllowNull()][string]$LastError = $null
    )

    $script:StartupStateSequence++
    $script:StartupStateStatus = $Status
    $now = [DateTime]::UtcNow
    $payload = [ordered]@{
        schemaVersion = 1
        mode = if ($Development) { "development" } else { "production" }
        status = $Status
        phase = $Phase
        attempt = $Attempt
        sequence = $script:StartupStateSequence
        startedAt = $script:LauncherStartedAt.ToString("o")
        updatedAt = $now.ToString("o")
        elapsedMs = [Math]::Round(($now - $script:LauncherStartedAt).TotalMilliseconds, 3)
        errorCode = $ErrorCode
        helpAction = ConvertTo-LuminaStateText -Text $HelpAction
        lastError = ConvertTo-LuminaStateText -Text $LastError
        logDirectory = "data/logs"
    }
    $temporaryPath = "$StartupStatePath.$PID.$($script:StartupStateSequence).tmp"
    $backupPath = "$StartupStatePath.bak"
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StartupStatePath) | Out-Null
        $json = $payload | ConvertTo-Json -Depth 4 -Compress
        $encoding = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($temporaryPath, $json, $encoding)
        if (Test-Path -LiteralPath $StartupStatePath) {
            Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
            [System.IO.File]::Replace($temporaryPath, $StartupStatePath, $backupPath)
            Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
        }
        else {
            [System.IO.File]::Move($temporaryPath, $StartupStatePath)
        }
    }
    catch {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
        # Diagnostics must never become the reason the launcher exits.
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command $($Arguments -join ' ')"
    }
}

function Stop-ProcessTree {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $taskkillPath = Join-Path $env:SystemRoot "System32\taskkill.exe"
    if (Test-Path -LiteralPath $taskkillPath) {
        try {
            & $taskkillPath /PID ([string]$ProcessId) /T /F 2>$null | Out-Null
        }
        catch {
            # Fall back to the PowerShell tree walk below.
        }
        if ($null -eq (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            return
        }
    }

    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $queue = [System.Collections.Generic.Queue[int]]::new()
    $tree = [System.Collections.Generic.List[int]]::new()
    $queue.Enqueue($ProcessId)
    while ($queue.Count -gt 0) {
        $currentId = $queue.Dequeue()
        if ($tree.Contains($currentId)) {
            continue
        }
        $tree.Add($currentId)
        foreach ($child in $processes | Where-Object { [int]$_.ParentProcessId -eq $currentId }) {
            $queue.Enqueue([int]$child.ProcessId)
        }
    }
    for ($index = $tree.Count - 1; $index -ge 0; $index--) {
        Stop-Process -Id $tree[$index] -Force -ErrorAction SilentlyContinue
    }
}

function Test-LuminaCommandLine {
    param(
        [AllowEmptyString()][string]$ProcessName,
        [AllowEmptyString()][string]$CommandLine
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }
    $executable = [System.IO.Path]::GetFileName($ProcessName).ToLowerInvariant()
    $supervisorScript = Join-Path $RepositoryRoot "devtools\run_lumina.ps1"
    $viteScript = Join-Path $RepositoryRoot "apps\web\node_modules\vite\bin\vite.js"
    return (
        ($executable -in @("powershell.exe", "pwsh.exe") -and
            $CommandLine.IndexOf($supervisorScript, [StringComparison]::OrdinalIgnoreCase) -ge 0) -or
        $CommandLine -match 'lumina\.main:app' -or
        ($executable -eq "node.exe" -and
            $CommandLine.IndexOf($viteScript, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    )
}

function Get-LuminaProcessRootId {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][hashtable]$ProcessesById
    )

    $currentId = $ProcessId
    $rootId = 0
    for ($depth = 0; $depth -lt 12 -and $currentId -gt 0; $depth++) {
        $process = $ProcessesById[$currentId]
        if ($null -eq $process) {
            break
        }
        if (Test-LuminaCommandLine `
            -ProcessName ([string]$process.Name) `
            -CommandLine ([string]$process.CommandLine)) {
            $rootId = $currentId
        }
        $currentId = [int]$process.ParentProcessId
    }
    return $rootId
}

function Stop-ExistingLuminaListeners {
    param([Parameter(Mandatory = $true)][int[]]$Ports)

    $connections = @(
        Get-NetTCPConnection -State Listen -LocalPort $Ports -ErrorAction SilentlyContinue
    )
    $processesById = @{}
    if ($connections.Count -gt 0) {
        foreach ($process in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
            $processesById[[int]$process.ProcessId] = $process
        }
    }
    $rootIds = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($connection in $connections) {
        $ownerId = [int]$connection.OwningProcess
        $rootId = Get-LuminaProcessRootId -ProcessId $ownerId -ProcessesById $processesById
        if ($rootId -le 0) {
            $owner = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
            $ownerName = if ($null -eq $owner) { "unknown" } else { $owner.ProcessName }
            throw "Port $($connection.LocalPort) is used by a non-Lumina process: $ownerName (PID $ownerId)"
        }
        [void]$rootIds.Add($rootId)
    }
    foreach ($rootId in $rootIds) {
        Write-Host "[Lumina] Stopping previous Lumina process tree (PID $rootId)..."
        Stop-ProcessTree -ProcessId $rootId
    }
    $remaining = @(
        Get-NetTCPConnection -State Listen -LocalPort $Ports -ErrorAction SilentlyContinue
    )
    if ($remaining.Count -gt 0) {
        throw "Lumina ports are still occupied after reset: $($remaining.LocalPort -join ', ')"
    }
}

function Stop-ManagedProcesses {
    param([switch]$PreserveFrontend)

    $processIds = @(
        $script:ManagedProcesses |
            Where-Object { -not $PreserveFrontend -or $_.Name -ne "Frontend" } |
            ForEach-Object { $_.Process.Id } |
            Sort-Object -Unique
    )
    foreach ($processId in $processIds) {
        Stop-ProcessTree -ProcessId $processId
    }
    $script:ManagedProcesses = @(
        $script:ManagedProcesses |
            Where-Object { $PreserveFrontend -and $_.Name -eq "Frontend" }
    )
}

function Stop-PreviousSupervisor {
    if (-not (Test-Path -LiteralPath $SupervisorPidPath)) {
        return
    }
    $previousPidText = [System.IO.File]::ReadAllText($SupervisorPidPath).Trim()
    $identityParts = $previousPidText -split '\|', 2
    $previousPid = 0
    if (-not [int]::TryParse($identityParts[0], [ref]$previousPid) -or $previousPid -eq $PID) {
        return
    }
    $previous = Get-Process -Id $previousPid -ErrorAction SilentlyContinue
    if ($null -eq $previous) {
        return
    }

    $matchesSupervisorIdentity = $false
    if ($identityParts.Count -eq 2) {
        $expectedStartTimeTicks = [long]0
        if ([long]::TryParse($identityParts[1], [ref]$expectedStartTimeTicks)) {
            try {
                $matchesSupervisorIdentity = (
                    $previous.StartTime.ToUniversalTime().Ticks -eq $expectedStartTimeTicks
                )
            }
            catch {
                $matchesSupervisorIdentity = $false
            }
        }
    }
    else {
        $legacyProcess = Get-CimInstance `
            Win32_Process `
            -Filter "ProcessId = $previousPid" `
            -ErrorAction SilentlyContinue
        $matchesSupervisorIdentity = (
            $null -ne $legacyProcess -and
            (Test-LuminaCommandLine `
                -ProcessName ([string]$legacyProcess.Name) `
                -CommandLine ([string]$legacyProcess.CommandLine))
        )
    }
    if ($matchesSupervisorIdentity) {
        Write-Host "[Lumina] Replacing the previous supervisor (PID $previousPid)..."
        Stop-ProcessTree -ProcessId $previousPid
    }
}

function Set-SupervisorPid {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $current = Get-Process -Id $PID -ErrorAction Stop
    $identity = "$PID|$($current.StartTime.ToUniversalTime().Ticks)"
    [System.IO.File]::WriteAllText($SupervisorPidPath, $identity, $utf8)
}

function Remove-SupervisorPid {
    if (-not (Test-Path -LiteralPath $SupervisorPidPath)) {
        return
    }
    $storedPid = ([System.IO.File]::ReadAllText($SupervisorPidPath).Trim() -split '\|', 2)[0]
    if ($storedPid -eq [string]$PID) {
        Remove-Item -LiteralPath $SupervisorPidPath -Force -ErrorAction SilentlyContinue
    }
}

function Start-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$OutputLog,
        [Parameter(Mandatory = $true)][string]$ErrorLog
    )

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OutputLog `
        -RedirectStandardError $ErrorLog `
        -PassThru
    return [pscustomobject]@{
        Name = $Name
        Process = $process
        ErrorLog = $ErrorLog
    }
}

function Get-ExitedManagedProcess {
    foreach ($managed in $script:ManagedProcesses) {
        $managed.Process.Refresh()
        if ($managed.Process.HasExited) {
            return $managed
        }
    }
    return $null
}

function Test-Endpoint {
    param([Parameter(Mandatory = $true)][string]$Uri)

    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Write-NewBackendActivity {
    if (-not (Test-Path -LiteralPath $BackendOutputLog)) {
        return
    }
    $lines = @(Get-Content -Encoding utf8 -LiteralPath $BackendOutputLog -ErrorAction SilentlyContinue)
    if ($script:BackendActivityLineCount -gt $lines.Count) {
        $script:BackendActivityLineCount = 0
    }
    if ($script:BackendActivityLineCount -ge $lines.Count) {
        return
    }
    for ($index = $script:BackendActivityLineCount; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match '^\(\d{2}:\d{2}:\d{2}\) \[Lumina\] LLM response ') {
            Write-Host $lines[$index]
        }
    }
    $script:BackendActivityLineCount = $lines.Count
}

function Get-LanIPv4Addresses {
    return @(
        Get-NetIPConfiguration -ErrorAction SilentlyContinue |
            Where-Object { $null -ne $_.IPv4DefaultGateway } |
            ForEach-Object { $_.IPv4Address.IPAddress } |
            Where-Object { $_ -and $_ -notmatch '^127\.' -and $_ -notmatch '^169\.254\.' } |
            Sort-Object -Unique
    )
}

function Test-LuminaHealthy {
    if (-not (Test-Endpoint -Uri "http://127.0.0.1:$BackendPort/api/health/ready")) {
        return $false
    }
    $frontendUri = if ($Development) {
        "http://127.0.0.1:$FrontendPort/"
    }
    else {
        "http://127.0.0.1:$BackendPort/"
    }
    return Test-Endpoint -Uri $frontendUri
}

function Test-HardResetInput {
    param(
        [char]$Character = [char]0,
        [int]$VirtualKeyCode = 0
    )

    return (
        $VirtualKeyCode -eq [int][ConsoleKey]::R -or
        $Character -ceq 'r' -or
        $Character -ceq 'R' -or
        [int]$Character -eq 0x3131
    )
}

function Test-HardResetKey {
    $keyCharacter = [char]0
    $virtualKeyCode = 0
    $keyWasRead = $false
    try {
        if ([Console]::KeyAvailable) {
            $keyInfo = [Console]::ReadKey($true)
            $keyCharacter = $keyInfo.KeyChar
            $virtualKeyCode = [int]$keyInfo.Key
            $keyWasRead = $true
        }
    }
    catch {
        $keyWasRead = $false
    }
    if (-not $keyWasRead) {
        try {
            if ($Host.UI.RawUI.KeyAvailable) {
                $options = (
                    [System.Management.Automation.Host.ReadKeyOptions]::NoEcho -bor
                    [System.Management.Automation.Host.ReadKeyOptions]::IncludeKeyDown
                )
                $keyInfo = $Host.UI.RawUI.ReadKey($options)
                $keyCharacter = $keyInfo.Character
                $virtualKeyCode = $keyInfo.VirtualKeyCode
            }
        }
        catch {
            return $false
        }
    }
    return Test-HardResetInput -Character $keyCharacter -VirtualKeyCode $virtualKeyCode
}

function Confirm-LuminaRuntimePrepared {
    if ($Development) {
        Write-Host "[Lumina] Applying development database migrations once..."
        Invoke-Checked -Command "uv" -Arguments @(
            "run", "--project", $ServerRoot,
            "alembic", "-c", (Join-Path $ServerRoot "alembic.ini"),
            "upgrade", "head"
        )
        return
    }

    $frontendEntry = Join-Path $WebRoot "dist/index.html"
    if (-not (Test-Path -LiteralPath $frontendEntry -PathType Leaf)) {
        throw (
            "Lumina Frontend build is missing. Run installer.bat before starting " +
            "the production launcher."
        )
    }
    Write-Host "[Lumina] Verifying the production database schema..."
    Invoke-Checked -Command "uv" -Arguments @(
        "run", "--project", $ServerRoot,
        "alembic", "-c", (Join-Path $ServerRoot "alembic.ini"),
        "current", "--check-heads"
    )
}

function Get-AutomaticRestartDelay {
    param([Parameter(Mandatory = $true)][int]$Attempt)

    $delays = @(1, 2, 5)
    $index = [Math]::Min([Math]::Max($Attempt, 1) - 1, $delays.Count - 1)
    return $delays[$index]
}

function Start-LuminaProcesses {
    param([switch]$PreserveFrontend)

    $ports = if ($Development -and -not $PreserveFrontend) { @($BackendPort, $FrontendPort) } else { @($BackendPort) }
    Stop-ExistingLuminaListeners -Ports $ports

    $backendArguments = @(
        "run", "--project", $ServerRoot,
        "uvicorn", "lumina.main:app",
        "--app-dir", (Join-Path $ServerRoot "src"),
        "--host", "127.0.0.1",
        "--port", [string]$BackendPort
    )
    $script:BackendActivityLineCount = 0
    $preservedProcesses = @($script:ManagedProcesses)
    $backendProcess = Start-ManagedProcess `
        -Name "Backend" `
        -FilePath "uv" `
        -Arguments $backendArguments `
        -WorkingDirectory $RepositoryRoot `
        -OutputLog $BackendOutputLog `
        -ErrorLog (Join-Path $LogRoot "backend.err.log")
    $script:ManagedProcesses = @($preservedProcesses) + @($backendProcess)
    if ($Development -and -not $PreserveFrontend) {
        $script:ManagedProcesses += Start-ManagedProcess `
            -Name "Frontend" `
            -FilePath "node" `
            -Arguments @(
                (Join-Path $WebRoot "node_modules/vite/bin/vite.js"),
                "--host", "0.0.0.0",
                "--port", [string]$FrontendPort,
                "--strictPort"
            ) `
            -WorkingDirectory $WebRoot `
            -OutputLog (Join-Path $LogRoot "frontend.out.log") `
            -ErrorLog (Join-Path $LogRoot "frontend.err.log")
    }
}

function Wait-LuminaReady {
    $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-HardResetKey) {
            return $false
        }
        $exited = Get-ExitedManagedProcess
        if ($null -ne $exited) {
            throw "$($exited.Name) exited during startup. See $($exited.ErrorLog)"
        }
        if (Test-LuminaHealthy) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Lumina did not become healthy within $StartupTimeoutSeconds seconds."
}

Set-Location -LiteralPath $RepositoryRoot
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
Write-LuminaBanner
Write-LuminaStartupState -Status "starting" -Phase "PREFLIGHT"

try {
    if (-not (Test-Path -LiteralPath (Join-Path $RepositoryRoot ".env"))) {
        Write-LuminaStartupState -Status "starting" -Phase "INSTALLING"
        Write-Host "[Lumina] .env is missing. Running the installer first..."
        & (Join-Path $PSScriptRoot "install_lumina.ps1")
    }

    $env:LUMINA_ENVIRONMENT = if ($Development) { "development" } else { "production" }
    Write-LuminaStartupState -Status "starting" -Phase "PREFLIGHT"
    if (-not $Development) {
        Confirm-LuminaRuntimePrepared
    }
    Stop-PreviousSupervisor
    if ($Development) {
        Confirm-LuminaRuntimePrepared
    }
    Set-SupervisorPid
}
catch {
    $preflightError = $_.Exception.Message
    $details = Get-LuminaLauncherErrorDetails -Phase "PREFLIGHT" -Message $preflightError
    Write-LuminaStartupState `
        -Status "failed" `
        -Phase "PREFLIGHT" `
        -ErrorCode $details.Code `
        -HelpAction $details.HelpAction `
        -LastError $preflightError
    throw
}
$resetReason = "initial startup"
$automaticRestartCount = 0

try {
    $preserveFrontend = $false
    while ($true) {
        $manualResetRequested = $false
        $readyAt = $null
        $attemptNumber = $automaticRestartCount + 1
        $currentPhase = "STARTING_PROCESSES"
        try {
            Write-LuminaStartupState `
                -Status "starting" `
                -Phase $currentPhase `
                -Attempt $attemptNumber
            Write-Host "[Lumina] Hard reset: $resetReason"
            Stop-ManagedProcesses -PreserveFrontend:$preserveFrontend
            Start-LuminaProcesses -PreserveFrontend:$preserveFrontend
            $currentPhase = "WAITING_FOR_READINESS"
            Write-LuminaStartupState `
                -Status "starting" `
                -Phase $currentPhase `
                -Attempt $attemptNumber
            if (-not (Wait-LuminaReady)) {
                $preserveFrontend = $false
                $resetReason = "manual request"
                $manualResetRequested = $true
                Write-LuminaStartupState `
                    -Status "restarting" `
                    -Phase "MANUAL_RESET" `
                    -Attempt $attemptNumber `
                    -HelpAction "Manual reset requested."
                continue
            }
            $preserveFrontend = $Development
            $readyAt = [DateTime]::UtcNow
            $currentPhase = "RUNNING"
            Write-LuminaStartupState `
                -Status "ready" `
                -Phase "READY" `
                -Attempt $attemptNumber
            Write-Host ""

            if ($Development) {
                foreach ($address in Get-LanIPv4Addresses) {
                    Write-Host -NoNewline "[Lumina] Frontend (network): "
                    Write-Host "http://${address}:$FrontendPort/" -ForegroundColor Green
                }
                Write-Host "[Lumina] Frontend (local):   http://127.0.0.1:$FrontendPort/"
                Write-Host "[Lumina] Backend (local):    http://127.0.0.1:$BackendPort/"
            }
            else {
                Write-Host "[Lumina] Service: http://127.0.0.1:$BackendPort"
            }
            $koreanResetKey = [char]0x3131
            Write-Host "[Lumina] Press r, R, or $koreanResetKey to hard reset Frontend and Backend."
            Write-Host "[Lumina] Logs: $LogRoot"

            $healthFailures = 0
            $nextHealthCheck = [DateTime]::UtcNow.AddSeconds($HealthCheckIntervalSeconds)
            while ($true) {
                Write-NewBackendActivity
                if (Test-HardResetKey) {
                    $preserveFrontend = $false
                    $resetReason = "manual request"
                    $manualResetRequested = $true
                    break
                }
                $exited = Get-ExitedManagedProcess
                if ($null -ne $exited) {
                    $resetReason = "$($exited.Name) exited unexpectedly"
                    if ($exited.Name -eq "Frontend") {
                        $preserveFrontend = $false
                    }
                    break
                }
                if ([DateTime]::UtcNow -ge $nextHealthCheck) {
                    if (Test-LuminaHealthy) {
                        $healthFailures = 0
                        if (
                            $automaticRestartCount -gt 0 -and
                            $null -ne $readyAt -and
                            ([DateTime]::UtcNow - $readyAt).TotalSeconds -ge $RestartBudgetResetSeconds
                        ) {
                            $automaticRestartCount = 0
                            $readyAt = [DateTime]::UtcNow
                        }
                    }
                    else {
                        $healthFailures++
                        Write-Warning "Lumina health check failed ($healthFailures/$HealthFailureThreshold)."
                        if ($healthFailures -ge $HealthFailureThreshold) {
                            $resetReason = "health check failed $healthFailures times"
                            break
                        }
                    }
                    $nextHealthCheck = [DateTime]::UtcNow.AddSeconds($HealthCheckIntervalSeconds)
                }
                Start-Sleep -Milliseconds 200
            }
        }
        catch {
            $resetReason = $_.Exception.Message
            Write-Warning "Lumina startup failed: $resetReason"
        }
        finally {
            Stop-ManagedProcesses -PreserveFrontend:$preserveFrontend
        }
        if ($manualResetRequested) {
            Write-LuminaStartupState `
                -Status "restarting" `
                -Phase "MANUAL_RESET" `
                -Attempt $attemptNumber `
                -HelpAction "Manual reset requested."
            continue
        }
        $details = Get-LuminaLauncherErrorDetails -Phase $currentPhase -Message $resetReason
        if ($automaticRestartCount -ge $MaxAutomaticRestarts) {
            Write-LuminaStartupState `
                -Status "exhausted" `
                -Phase $currentPhase `
                -Attempt $attemptNumber `
                -ErrorCode "RESTART_EXHAUSTED" `
                -HelpAction $details.HelpAction `
                -LastError $resetReason
            throw (
                "Lumina exhausted its automatic restart budget after " +
                "$MaxAutomaticRestarts retries. Last failure: $resetReason. " +
                "See logs in $LogRoot."
            )
        }
        $automaticRestartCount++
        $restartDelay = Get-AutomaticRestartDelay -Attempt $automaticRestartCount
        Write-LuminaStartupState `
            -Status "restarting" `
            -Phase $currentPhase `
            -Attempt $attemptNumber `
            -ErrorCode $details.Code `
            -HelpAction $details.HelpAction `
            -LastError $resetReason
        Write-Host (
            "[Lumina] Restarting in $restartDelay second(s) " +
            "($automaticRestartCount/$MaxAutomaticRestarts)..."
        )
        Start-Sleep -Seconds $restartDelay
    }
}
finally {
    Stop-ManagedProcesses
    Remove-SupervisorPid
    if ($script:StartupStateStatus -notin @("failed", "exhausted")) {
        Write-LuminaStartupState -Status "stopped" -Phase "STOPPED"
    }
}
