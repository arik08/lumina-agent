$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "stop_lumina.ps1"
$batchPath = Join-Path $PSScriptRoot "stop_lumina.bat"
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -gt 0) {
    throw "stop_lumina.ps1 has parser errors: $($errors.Message -join '; ')"
}

$batchContent = Get-Content -LiteralPath $batchPath -Raw
foreach ($expectedBatchFragment in @(
    'pushd "%TEMP%"',
    '"%~dp0stop_lumina.ps1" %*',
    'exit /b %LUMINA_STOP_EXIT%'
)) {
    if ($batchContent.IndexOf($expectedBatchFragment, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "stop_lumina.bat is missing required fragment: $expectedBatchFragment"
    }
}

$functionNames = @(
    "Test-CommandLineContainsPath",
    "Test-LuminaRuntimeProcess",
    "Get-LuminaRootProcessIds",
    "Stop-ProcessTree"
)
foreach ($functionName in $functionNames) {
    $functionAst = $ast.Find(
        {
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq $functionName
        },
        $true
    )
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ServerRoot = Join-Path $RepositoryRoot "apps\server"
$SupervisorScript = Join-Path $PSScriptRoot "run_lumina.ps1"
$ProductionLauncher = Join-Path $RepositoryRoot "run_lumina.bat"
$DevelopmentLauncher = Join-Path $RepositoryRoot "run_lumina_dev.bat"
$ViteScript = Join-Path $RepositoryRoot "apps\web\node_modules\vite\bin\vite.js"

$cases = @(
    @{
        Name = "production batch launcher"
        ProcessName = "cmd.exe"
        CommandLine = "cmd.exe /c `"$ProductionLauncher`""
        Expected = $true
    },
    @{
        Name = "PowerShell supervisor"
        ProcessName = "powershell.exe"
        CommandLine = "powershell -NoProfile -File `"$SupervisorScript`" -Development"
        Expected = $true
    },
    @{
        Name = "Lumina backend"
        ProcessName = "python.exe"
        CommandLine = "python -m uvicorn lumina.main:app --app-dir `"$ServerRoot\src`""
        Expected = $true
    },
    @{
        Name = "Lumina Vite frontend"
        ProcessName = "node.exe"
        CommandLine = "node `"$ViteScript`" --port 5252"
        Expected = $true
    },
    @{
        Name = "foreign backend with the same module name"
        ProcessName = "python.exe"
        CommandLine = "python -m uvicorn lumina.main:app --app-dir C:\other\server\src"
        Expected = $false
    },
    @{
        Name = "repository Python utility"
        ProcessName = "python.exe"
        CommandLine = "`"$ServerRoot\.venv\Scripts\python.exe`" -"
        Expected = $false
    },
    @{
        Name = "PowerShell reading the launcher file"
        ProcessName = "pwsh.exe"
        CommandLine = "pwsh -Command Get-Content -LiteralPath `"$SupervisorScript`""
        Expected = $false
    },
    @{
        Name = "unrelated Node process"
        ProcessName = "node.exe"
        CommandLine = "node C:\other\vite\bin\vite.js"
        Expected = $false
    }
)
foreach ($case in $cases) {
    $actual = Test-LuminaRuntimeProcess `
        -ProcessName $case.ProcessName `
        -CommandLine $case.CommandLine
    if ($actual -ne $case.Expected) {
        throw "$($case.Name): expected $($case.Expected), got $actual"
    }
}

# The public preview path must remain runnable without changing process state.
& $scriptPath -WhatIf | Out-Null
& $batchPath -WhatIf | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "stop_lumina.bat -WhatIf failed with exit code $LASTEXITCODE."
}

$fakeProcesses = @(
    [pscustomobject]@{
        ProcessId = 100
        ParentProcessId = 1
        Name = "cmd.exe"
        CommandLine = "cmd.exe /c `"$DevelopmentLauncher`""
    },
    [pscustomobject]@{
        ProcessId = 101
        ParentProcessId = 100
        Name = "powershell.exe"
        CommandLine = "powershell -File `"$SupervisorScript`" -Development"
    },
    [pscustomobject]@{
        ProcessId = 102
        ParentProcessId = 101
        Name = "uv.exe"
        CommandLine = "uv run --project `"$ServerRoot`" uvicorn lumina.main:app"
    },
    [pscustomobject]@{
        ProcessId = 103
        ParentProcessId = 101
        Name = "node.exe"
        CommandLine = "node `"$ViteScript`""
    },
    [pscustomobject]@{
        ProcessId = 200
        ParentProcessId = 1
        Name = "node.exe"
        CommandLine = "node `"$ViteScript`""
    },
    [pscustomobject]@{
        ProcessId = 300
        ParentProcessId = 1
        Name = "python.exe"
        CommandLine = "python -m uvicorn lumina.main:app --app-dir C:\other\server\src"
    }
)
$rootIds = @(Get-LuminaRootProcessIds -Processes $fakeProcesses)
if ($rootIds.Count -ne 2 -or $rootIds[0] -ne 100 -or $rootIds[1] -ne 200) {
    throw "Expected deduplicated Lumina root PIDs 100 and 200, got $($rootIds -join ', ')."
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

    Stop-ProcessTree -ProcessId $treeParent.Id
    if ($null -ne (Get-Process -Id $treeParent.Id -ErrorAction SilentlyContinue)) {
        throw "Stop-ProcessTree left the test parent process running."
    }
    if ($null -ne (Get-Process -Id $treeChildId -ErrorAction SilentlyContinue)) {
        throw "Stop-ProcessTree left the test child process running."
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

Write-Host "stop_lumina tests passed ($($cases.Count) matcher cases, batch wrapper, root deduplication, and process-tree cleanup)."
