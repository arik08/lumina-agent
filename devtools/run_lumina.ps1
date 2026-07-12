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
$StartupTimeoutSeconds = 60
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
    param([AllowEmptyString()][string]$CommandLine)

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }
    return (
        $CommandLine.IndexOf($RepositoryRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
        $CommandLine -match 'lumina\.main:app'
    )
}

function Get-LuminaProcessRootId {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $currentId = $ProcessId
    $rootId = 0
    for ($depth = 0; $depth -lt 12 -and $currentId -gt 0; $depth++) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $currentId" -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            break
        }
        if (Test-LuminaCommandLine -CommandLine ([string]$process.CommandLine)) {
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
    $rootIds = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($connection in $connections) {
        $ownerId = [int]$connection.OwningProcess
        $rootId = Get-LuminaProcessRootId -ProcessId $ownerId
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
    if ($rootIds.Count -gt 0) {
        Start-Sleep -Milliseconds 800
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
    $previousPid = 0
    if (-not [int]::TryParse($previousPidText, [ref]$previousPid) -or $previousPid -eq $PID) {
        return
    }
    $previous = Get-CimInstance Win32_Process -Filter "ProcessId = $previousPid" -ErrorAction SilentlyContinue
    if (
        $null -ne $previous -and
        (Test-LuminaCommandLine -CommandLine ([string]$previous.CommandLine))
    ) {
        Write-Host "[Lumina] Replacing the previous supervisor (PID $previousPid)..."
        Stop-ProcessTree -ProcessId $previousPid
        Start-Sleep -Milliseconds 800
    }
}

function Set-SupervisorPid {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($SupervisorPidPath, [string]$PID, $utf8)
}

function Remove-SupervisorPid {
    if (-not (Test-Path -LiteralPath $SupervisorPidPath)) {
        return
    }
    if ([System.IO.File]::ReadAllText($SupervisorPidPath).Trim() -eq [string]$PID) {
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

function Test-HardResetKey {
    $keyCharacter = $null
    try {
        if ([Console]::KeyAvailable) {
            $keyCharacter = [Console]::ReadKey($true).KeyChar
        }
    }
    catch {
        $keyCharacter = $null
    }
    if ($null -eq $keyCharacter) {
        try {
            if ($Host.UI.RawUI.KeyAvailable) {
                $options = (
                    [System.Management.Automation.Host.ReadKeyOptions]::NoEcho -bor
                    [System.Management.Automation.Host.ReadKeyOptions]::IncludeKeyDown
                )
                $keyCharacter = $Host.UI.RawUI.ReadKey($options).Character
            }
        }
        catch {
            $keyCharacter = $null
        }
    }
    return (
        $keyCharacter -eq 'r' -or
        $keyCharacter -eq 'R' -or
        [int]$keyCharacter -eq 0x3131
    )
}

function Start-LuminaProcesses {
    param([switch]$PreserveFrontend)

    $ports = if ($Development -and -not $PreserveFrontend) { @($BackendPort, $FrontendPort) } else { @($BackendPort) }
    Stop-ExistingLuminaListeners -Ports $ports

    Invoke-Checked -Command "uv" -Arguments @(
        "run", "--project", $ServerRoot,
        "alembic", "-c", (Join-Path $ServerRoot "alembic.ini"),
        "upgrade", "head"
    )
    if (-not $Development) {
        Invoke-Checked -Command "npm" -Arguments @("run", "build", "--prefix", $WebRoot)
    }

    $backendArguments = @(
        "run", "--project", $ServerRoot,
        "uvicorn", "lumina.main:app",
        "--app-dir", (Join-Path $ServerRoot "src"),
        "--host", "127.0.0.1",
        "--port", [string]$BackendPort
    )
    if ($Development) {
        $backendArguments += "--reload"
    }
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
            throw "Manual hard reset requested during startup."
        }
        $exited = Get-ExitedManagedProcess
        if ($null -ne $exited) {
            throw "$($exited.Name) exited during startup. See $($exited.ErrorLog)"
        }
        if (Test-LuminaHealthy) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Lumina did not become healthy within $StartupTimeoutSeconds seconds."
}

Set-Location -LiteralPath $RepositoryRoot
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
Write-LuminaBanner

if (-not (Test-Path -LiteralPath (Join-Path $RepositoryRoot ".env"))) {
    Write-Host "[Lumina] .env is missing. Running the installer first..."
    & (Join-Path $PSScriptRoot "install_lumina.ps1")
}

Stop-PreviousSupervisor
Set-SupervisorPid
$env:LUMINA_ENVIRONMENT = if ($Development) { "development" } else { "production" }
$resetReason = "initial startup"

try {
    $preserveFrontend = $false
    while ($true) {
        try {
            Write-Host "[Lumina] Hard reset: $resetReason"
            Stop-ManagedProcesses -PreserveFrontend:$preserveFrontend
            Start-LuminaProcesses -PreserveFrontend:$preserveFrontend
            Wait-LuminaReady
            $preserveFrontend = $Development
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
            Write-Host "[Lumina] Press  R to hard reset."
            Write-Host "[Lumina] Logs: $LogRoot"

            $healthFailures = 0
            $nextHealthCheck = [DateTime]::UtcNow.AddSeconds($HealthCheckIntervalSeconds)
            while ($true) {
                Write-NewBackendActivity
                if (Test-HardResetKey) {
                    $resetReason = "manual request"
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
        Write-Host "[Lumina] Restarting in 1 second..."
        Start-Sleep -Seconds 1
    }
}
finally {
    Stop-ManagedProcesses
    Remove-SupervisorPid
}
