function Get-LuminaDotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }
    $content = [System.IO.File]::ReadAllText($Path)
    $inlineSpace = "[^\S\r\n]*"
    $pattern = "(?m)^" + $inlineSpace + [regex]::Escape($Key) + $inlineSpace + "=" + $inlineSpace + "(.*)$"
    $match = [regex]::Match($content, $pattern)
    if (-not $match.Success) {
        return ""
    }
    $value = $match.Groups[1].Value.Trim()
    if ($value.Length -ge 2 -and (
        ($value.StartsWith('"') -and $value.EndsWith('"')) -or
        ($value.StartsWith("'") -and $value.EndsWith("'"))
    )) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    return $value.Replace('\"', '"').Replace('\\', '\')
}

function Set-LuminaDotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )
    if ($Value.Contains("`r") -or $Value.Contains("`n")) {
        throw "Environment value for '$Key' must be a single line."
    }
    $encoded = $Value
    if ($Value -notmatch '^[A-Za-z0-9_./:@+\-]*$') {
        $encoded = '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
    }
    $content = if (Test-Path -LiteralPath $Path) {
        [System.IO.File]::ReadAllText($Path)
    }
    else {
        ""
    }
    $inlineSpace = "[^\S\r\n]*"
    $pattern = "(?m)^(" + $inlineSpace + [regex]::Escape($Key) + $inlineSpace + "=).*$"
    if ([regex]::IsMatch($content, $pattern)) {
        $content = [regex]::Replace(
            $content,
            $pattern,
            { param($match) $match.Groups[1].Value + $encoded }
        )
    }
    else {
        if ($content.Length -gt 0 -and -not $content.EndsWith("`n")) {
            $content += [Environment]::NewLine
        }
        $content += "$Key=$encoded" + [Environment]::NewLine
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $content, $utf8)
}

