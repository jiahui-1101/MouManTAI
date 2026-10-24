param([Parameter(Mandatory=$true)][string]$PythonPath)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskCredentialPath = Join-Path $env:LOCALAPPDATA 'MouManTAI-Demo-UAT/demo-db-password.dpapi'
$taskEncrypted = [IO.File]::ReadAllBytes($taskCredentialPath)
$taskDecrypted = [System.Security.Cryptography.ProtectedData]::Unprotect(
    $taskEncrypted, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
$taskNames = @('DATABASE_URL','MOUMANTAI_SYNTHETIC_MODE','MOUMANTAI_ORDERS_DEMO','ENVIRONMENT','CORS_ORIGINS')
$taskPrevious = @{}
foreach ($taskName in $taskNames) { $taskPrevious[$taskName] = [Environment]::GetEnvironmentVariable($taskName,'Process') }
try {
    $taskPassword = [Text.Encoding]::UTF8.GetString($taskDecrypted)
    $env:DATABASE_URL = 'postgresql+psycopg://moumantai_demo:' + [Uri]::EscapeDataString($taskPassword) + '@127.0.0.1:5434/moumantai_demo'
    $env:MOUMANTAI_SYNTHETIC_MODE = '1'
    $env:MOUMANTAI_ORDERS_DEMO = '1'
    $env:ENVIRONMENT = 'development'
    $env:CORS_ORIGINS = 'http://127.0.0.1:5175,http://localhost:5175'
    $taskProcess = Start-Process -FilePath $PythonPath -ArgumentList @('-B','scripts/run_orders_readonly_demo.py') `
        -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $taskRoot 'orders-demo-runtime.log') `
        -RedirectStandardError (Join-Path $taskRoot 'orders-demo-runtime-error.log')
    Write-Output ('Read-only demo launcher PID ' + $taskProcess.Id)
} finally {
    foreach ($taskName in $taskNames) { [Environment]::SetEnvironmentVariable($taskName,$taskPrevious[$taskName],'Process') }
    [Array]::Clear($taskDecrypted,0,$taskDecrypted.Length)
    $taskPassword = $null
}
