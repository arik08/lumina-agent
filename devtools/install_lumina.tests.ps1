$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "install_lumina.ps1"
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -gt 0) {
    throw "install_lumina.ps1 has parser errors: $($errors.Message -join '; ')"
}

$functionAst = $ast.Find(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Read-LuminaYesNoChoice"
    },
    $true
)
if ($null -eq $functionAst) {
    throw "Read-LuminaYesNoChoice was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$cases = @(
    @{ Name = "uppercase Y"; Key = "Y"; Character = "Y"; Expected = $true },
    @{ Name = "lowercase y"; Key = "Y"; Character = "y"; Expected = $true },
    @{ Name = "uppercase N"; Key = "N"; Character = "N"; Expected = $false },
    @{ Name = "lowercase n"; Key = "N"; Character = "n"; Expected = $false },
    @{ Name = "physical Y under IME"; Key = "Y"; Character = [char]0x315B; Expected = $true },
    @{ Name = "physical N under IME"; Key = "N"; Character = [char]0x315C; Expected = $false }
)
foreach ($case in $cases) {
    $script:testKey = [pscustomobject]@{
        Key = $case.Key
        KeyChar = $case.Character
    }
    $actual = Read-LuminaYesNoChoice -Prompt "test" -ReadKey { $script:testKey }
    if ($actual -ne $case.Expected) {
        throw "$($case.Name): expected $($case.Expected), got $actual"
    }
}

$script:keyQueue = [System.Collections.Generic.Queue[object]]::new()
$script:keyQueue.Enqueue([pscustomobject]@{ Key = "A"; KeyChar = "a" })
$script:keyQueue.Enqueue([pscustomobject]@{ Key = "N"; KeyChar = "n" })
$actualAfterInvalidKey = Read-LuminaYesNoChoice `
    -Prompt "test" `
    -ReadKey { $script:keyQueue.Dequeue() }
if ($actualAfterInvalidKey -ne $false) {
    throw "Unexpected keys must be ignored until Y or N is pressed."
}

Write-Host "install_lumina tests passed ($($cases.Count) Y/N key cases and invalid-key retry)."
