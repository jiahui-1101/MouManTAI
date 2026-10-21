param([Parameter(Mandatory = $true)][string]$Path)
# Dot-source from the repository root. Only P1_ keys are loaded; values are never printed.
foreach ($p1Line in Get-Content -LiteralPath $Path) {
    if ($p1Line -match '^\s*(#|$)') { continue }
    if ($p1Line -notmatch '^(P1_[A-Z0-9_]+)=(.*)$') { throw 'Invalid P1 environment file line' }
    [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
}
