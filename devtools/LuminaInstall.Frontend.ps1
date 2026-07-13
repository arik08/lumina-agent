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

function Assert-LuminaFrontendNativeModulesUnlocked {
    param([Parameter(Mandatory = $true)][string]$WebRoot)

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
