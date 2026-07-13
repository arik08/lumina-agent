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

Write-Host "run_lumina tests passed ($($cases.Count) key cases, 2 reset paths, fast and identity-safe process cleanup)."
