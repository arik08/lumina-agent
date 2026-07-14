[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "LuminaLauncher.Input.ps1")

try {
    $keyInfo = [Console]::ReadKey($true)
    if (
        Test-HardResetInput `
            -Character $keyInfo.KeyChar `
            -VirtualKeyCode ([int]$keyInfo.Key)
    ) {
        exit 75
    }
}
catch {
    # A redirected or detached console cannot provide an interactive restart key.
}

exit 0
