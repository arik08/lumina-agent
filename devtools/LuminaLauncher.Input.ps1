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
