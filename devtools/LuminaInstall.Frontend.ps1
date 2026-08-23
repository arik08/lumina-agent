function Get-LuminaLockedNativeModules {
    param([Parameter(Mandatory = $true)][string]$WebRoot)

    if ($env:OS -ne "Windows_NT") {
        return @()
    }
    $nodeModules = Join-Path $WebRoot "node_modules"
    if (-not (Test-Path -LiteralPath $nodeModules -PathType Container)) {
        return @()
    }

    $locked = [System.Collections.Generic.List[string]]::new()
    foreach ($module in @(Get-ChildItem -LiteralPath $nodeModules -Filter "*.node" -File -Recurse -ErrorAction SilentlyContinue)) {
        $stream = $null
        try {
            $stream = [System.IO.File]::Open(
                $module.FullName,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::None
            )
        }
        catch {
            $locked.Add($module.FullName)
        }
        finally {
            if ($null -ne $stream) {
                $stream.Dispose()
            }
        }
    }
    return @($locked)
}

function Get-LuminaFrontendViteProcesses {
    param(
        [Parameter(Mandatory = $true)][string]$WebRoot,
        [AllowNull()][object[]]$Processes = $null
    )

    if ($env:OS -ne "Windows_NT") {
        return @()
    }
    if ($null -eq $Processes) {
        $Processes = @(
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
        )
    }

    $resolvedWebRoot = [System.IO.Path]::GetFullPath($WebRoot).TrimEnd('\', '/')
    $repositoryRoot = [System.IO.Path]::GetFullPath(
        (Split-Path -Parent (Split-Path -Parent $resolvedWebRoot))
    ).TrimEnd('\', '/')
    $workspacePaths = @($resolvedWebRoot, $repositoryRoot)
    $processById = @{}
    foreach ($process in @($Processes)) {
        $processById[[int]$process.ProcessId] = $process
    }

    $viteMatches = [System.Collections.Generic.List[object]]::new()
    foreach ($process in @($Processes)) {
        $processExecutableName = [System.IO.Path]::GetFileName([string]$process.ExecutablePath)
        if ($processExecutableName -notmatch "^(?i:node(?:\.exe)?)$") {
            continue
        }
        $commandLine = [string]$process.CommandLine
        if ([string]::IsNullOrWhiteSpace($commandLine) -or
            $commandLine -notmatch "(?i)(?:^|[\\/\s`"'])vite(?:\.js)?(?:[\\/\s`"']|$)") {
            continue
        }

        $current = $process
        $visited = [System.Collections.Generic.HashSet[int]]::new()
        while ($null -ne $current -and $visited.Add([int]$current.ProcessId)) {
            $processText = ([string]$current.ExecutablePath) + "`n" + ([string]$current.CommandLine)
            $belongsToWorkspace = $false
            foreach ($workspacePath in $workspacePaths) {
                if ($processText.IndexOf($workspacePath, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                    $belongsToWorkspace = $true
                    break
                }
            }
            if ($belongsToWorkspace) {
                $viteMatches.Add($process)
                break
            }

            $parentId = [int]$current.ParentProcessId
            $current = if ($processById.ContainsKey($parentId)) {
                $processById[$parentId]
            }
            else {
                $null
            }
        }
    }
    return @($viteMatches)
}

function Assert-LuminaFrontendNativeModulesUnlocked {
    param(
        [Parameter(Mandatory = $true)][string]$WebRoot,
        [AllowNull()][object[]]$Processes = $null
    )

    $viteProcesses = @(Get-LuminaFrontendViteProcesses -WebRoot $WebRoot -Processes $Processes)
    if ($viteProcesses.Count -gt 0) {
        $processHints = @($viteProcesses | ForEach-Object { "PID $($_.ProcessId)" })
        throw (
            "Frontend dependency installation cannot run while this Lumina workspace's Vite frontend is active. " +
            "Stop the Lumina frontend process(es) and retry: " + ($processHints -join ", ") + "."
        )
    }

    $locked = @(Get-LuminaLockedNativeModules -WebRoot $WebRoot)
    if ($locked.Count -eq 0) {
        return
    }

    $nodeProcesses = @(
        Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace([string]$_.CommandLine) -and
                ([string]$_.CommandLine).IndexOf(
                    $WebRoot,
                    [StringComparison]::OrdinalIgnoreCase
                ) -ge 0
            } |
            ForEach-Object { "PID $($_.ProcessId)" }
    )
    $processHint = if ($nodeProcesses.Count -gt 0) {
        " Workspace Node processes: $($nodeProcesses -join ',')."
    }
    else {
        " Close any running Lumina/Vite frontend before retrying."
    }
    throw (
        "Frontend dependency installation cannot replace locked native module(s): " +
        ($locked -join ", ") + "." + $processHint
    )
}

function Invoke-LuminaNpmCommandWithOutput {
    param(
        [Parameter(Mandatory = $true)][string]$NpmCommand,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $lines = [System.Collections.Generic.List[string]]::new()
    & $NpmCommand @Arguments 2>&1 | ForEach-Object {
        $line = [string]$_
        $lines.Add($line)
        Write-Host $line
    }
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output = $lines -join "`n"
    }
}

function Install-LuminaFrontendDependencies {
    param(
        [Parameter(Mandatory = $true)][string]$NpmCommand,
        [Parameter(Mandatory = $true)][string]$WebRoot,
        [switch]$NoNetwork,
        [AllowNull()][object[]]$Processes = $null
    )

    Assert-LuminaFrontendNativeModulesUnlocked -WebRoot $WebRoot -Processes $Processes
    $ciArguments = @("ci", "--prefix", $WebRoot)
    if ($NoNetwork) {
        $ciArguments += @("--offline", "--no-audit")
    }
    $ciResult = Invoke-LuminaNpmCommandWithOutput -NpmCommand $NpmCommand -Arguments $ciArguments
    if ($ciResult.ExitCode -eq 0) {
        return
    }
    if ($ciResult.Output -notmatch "(?im)\bEBUSY\b") {
        throw "Command '$NpmCommand' failed with exit code $($ciResult.ExitCode)."
    }

    Write-Warning (
        "npm ci could not replace a locked node_modules entry (EBUSY). " +
        "Retrying without changing package-lock.json."
    )
    $installArguments = @("install", "--package-lock=false", "--prefix", $WebRoot)
    if ($NoNetwork) {
        $installArguments += @("--offline", "--no-audit")
    }
    $installResult = Invoke-LuminaNpmCommandWithOutput `
        -NpmCommand $NpmCommand `
        -Arguments $installArguments
    if ($installResult.ExitCode -ne 0) {
        throw "Command '$NpmCommand' failed with exit code $($installResult.ExitCode)."
    }

    Write-Host "[Lumina] Validating fallback frontend dependencies..."
    $validationResult = Invoke-LuminaNpmCommandWithOutput `
        -NpmCommand $NpmCommand `
        -Arguments @("ls", "--prefix", $WebRoot)
    if ($validationResult.ExitCode -ne 0) {
        throw "Command '$NpmCommand' failed with exit code $($validationResult.ExitCode)."
    }
}
