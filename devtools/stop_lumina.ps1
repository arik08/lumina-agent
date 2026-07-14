[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "stop_lumina.ps1 supports the Windows Lumina launcher only."
}

# Avoid PowerShell 5 forwarding the script-level -WhatIf preference while it
# auto-imports CimCmdlets and reporting unrelated alias setup as cleanup work.
$savedWhatIfPreference = $WhatIfPreference
try {
    $WhatIfPreference = $false
    Import-Module CimCmdlets -ErrorAction Stop
}
finally {
    $WhatIfPreference = $savedWhatIfPreference
}

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ServerRoot = Join-Path $RepositoryRoot "apps\server"
$SupervisorScript = Join-Path $PSScriptRoot "run_lumina.ps1"
$ProductionLauncher = Join-Path $RepositoryRoot "run_lumina.bat"
$DevelopmentLauncher = Join-Path $RepositoryRoot "run_lumina_dev.bat"
$ViteScript = Join-Path $RepositoryRoot "apps\web\node_modules\vite\bin\vite.js"
$LogRoot = Join-Path $RepositoryRoot "data\logs"

function Test-CommandLineContainsPath {
    param(
        [AllowEmptyString()][string]$CommandLine,
        [Parameter(Mandatory = $true)][string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }
    $normalizedCommandLine = $CommandLine.Replace('/', '\')
    $normalizedPath = $Path.Replace('/', '\')
    return $normalizedCommandLine.IndexOf(
        $normalizedPath,
        [StringComparison]::OrdinalIgnoreCase
    ) -ge 0
}

function Test-LuminaRuntimeProcess {
    param(
        [AllowEmptyString()][string]$ProcessName,
        [AllowEmptyString()][string]$CommandLine
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }
    $executable = [System.IO.Path]::GetFileName($ProcessName).ToLowerInvariant()

    if (
        $executable -in @("powershell.exe", "pwsh.exe") -and
        $CommandLine -match '(?i)(?:^|\s)-(?:file|f)(?:\s|$)' -and
        (Test-CommandLineContainsPath -CommandLine $CommandLine -Path $SupervisorScript)
    ) {
        return $true
    }
    if (
        $executable -eq "cmd.exe" -and
        (
            (Test-CommandLineContainsPath -CommandLine $CommandLine -Path $ProductionLauncher) -or
            (Test-CommandLineContainsPath -CommandLine $CommandLine -Path $DevelopmentLauncher)
        )
    ) {
        return $true
    }
    if (
        $executable -in @("uv.exe", "python.exe", "pythonw.exe") -and
        $CommandLine -match 'lumina\.main:app' -and
        (Test-CommandLineContainsPath -CommandLine $CommandLine -Path $ServerRoot)
    ) {
        return $true
    }
    return (
        $executable -eq "node.exe" -and
        (Test-CommandLineContainsPath -CommandLine $CommandLine -Path $ViteScript)
    )
}

function Get-LuminaRootProcessIds {
    param([Parameter(Mandatory = $true)][object[]]$Processes)

    $processesById = @{}
    $matchedIds = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($process in $Processes) {
        $processId = [int]$process.ProcessId
        $processesById[$processId] = $process
        if (
            Test-LuminaRuntimeProcess `
                -ProcessName ([string]$process.Name) `
                -CommandLine ([string]$process.CommandLine)
        ) {
            [void]$matchedIds.Add($processId)
        }
    }

    $rootIds = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($matchedId in $matchedIds) {
        $rootId = $matchedId
        $currentId = $matchedId
        for ($depth = 0; $depth -lt 32 -and $currentId -gt 0; $depth++) {
            $process = $processesById[$currentId]
            if ($null -eq $process) {
                break
            }
            $parentId = [int]$process.ParentProcessId
            if ($matchedIds.Contains($parentId)) {
                $rootId = $parentId
            }
            $currentId = $parentId
        }
        [void]$rootIds.Add($rootId)
    }
    return @($rootIds | Sort-Object)
}

function Stop-ProcessTree {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $taskkillPath = Join-Path $env:SystemRoot "System32\taskkill.exe"
    if (Test-Path -LiteralPath $taskkillPath) {
        try {
            & $taskkillPath /PID ([string]$ProcessId) /T /F 2>$null | Out-Null
        }
        catch {
            # Fall back to a child-first PowerShell process walk.
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

$stoppedAny = $false
for ($pass = 1; $pass -le 3; $pass++) {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $rootIds = @(Get-LuminaRootProcessIds -Processes $processes)
    if ($rootIds.Count -eq 0) {
        break
    }

    $processesById = @{}
    foreach ($process in $processes) {
        $processesById[[int]$process.ProcessId] = $process
    }
    $stoppedThisPass = $false
    foreach ($rootId in $rootIds) {
        $process = $processesById[$rootId]
        $name = if ($null -eq $process) { "process" } else { [string]$process.Name }
        $target = "$name (PID $rootId)"
        if ($PSCmdlet.ShouldProcess($target, "Stop Lumina process tree")) {
            Write-Host "[Lumina] Stopping $target..."
            Stop-ProcessTree -ProcessId $rootId
            $stoppedAny = $true
            $stoppedThisPass = $true
        }
    }
    if (-not $stoppedThisPass) {
        return
    }
}

$remainingProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop)
$remainingIds = @(Get-LuminaRootProcessIds -Processes $remainingProcesses)
if ($remainingIds.Count -gt 0) {
    throw "Lumina process cleanup did not finish. Remaining root PID(s): $($remainingIds -join ', ')"
}

foreach ($pidFile in @("run_lumina.pid", "run_lumina_dev.pid")) {
    $pidPath = Join-Path $LogRoot $pidFile
    if (
        (Test-Path -LiteralPath $pidPath) -and
        $PSCmdlet.ShouldProcess($pidPath, "Remove stale Lumina supervisor PID file")
    ) {
        Remove-Item -LiteralPath $pidPath -Force
    }
}

if ($stoppedAny) {
    Write-Host "[Lumina] All Lumina background processes were stopped."
}
else {
    Write-Host "[Lumina] No Lumina background processes are running."
}
