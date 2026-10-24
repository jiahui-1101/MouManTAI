param([string]$PythonPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend/.venv/Scripts/python.exe'))
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Provide an existing backend virtualenv PythonPath.' }
if (Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8001 occupied; inspect existing runtime. Nothing restarted.' }
$taskNames = @('DATABASE_URL','MOUMANTAI_SYNTHETIC_MODE','MOUMANTAI_ORDERS_DEMO','ENVIRONMENT','CORS_ORIGINS')
$taskPrevious = @{}
foreach ($taskName in $taskNames) { $taskPrevious[$taskName] = [Environment]::GetEnvironmentVariable($taskName,'Process') }
$taskDecrypted = $null
try {
    # Portable option: caller supplies DATABASE_URL in process memory. The Python
    # launcher validates the exact isolated Demo target before connecting.
    if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
        $taskCredentialPath = Join-Path $env:LOCALAPPDATA 'MouManTAI-Demo-UAT/demo-db-password.dpapi'
        if (-not (Test-Path -LiteralPath $taskCredentialPath -PathType Leaf)) {
            throw 'Set DATABASE_URL securely in this process, or provision local DPAPI Demo credentials. Never copy another user''s DPAPI file.'
        }
        $taskEncrypted = [IO.File]::ReadAllBytes($taskCredentialPath)
        $taskDecrypted = [System.Security.Cryptography.ProtectedData]::Unprotect(
            $taskEncrypted, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
        $taskPassword = [Text.Encoding]::UTF8.GetString($taskDecrypted)
        $env:DATABASE_URL = 'postgresql+psycopg://moumantai_demo:' + [Uri]::EscapeDataString($taskPassword) + '@127.0.0.1:5434/moumantai_demo'
    }
    $env:MOUMANTAI_SYNTHETIC_MODE = '1'
    $env:MOUMANTAI_ORDERS_DEMO = '1'
    $env:ENVIRONMENT = 'development'
    $env:CORS_ORIGINS = 'http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:5175,http://localhost:5175'
    $taskLogs = Join-Path $env:LOCALAPPDATA 'MouManTAI-Demo-UAT'
    New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
    $taskProcess = Start-Process -FilePath $PythonPath -ArgumentList @('-B','scripts/run_orders_readonly_demo.py') `
        -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $taskLogs 'orders-demo-runtime.log') `
        -RedirectStandardError (Join-Path $taskLogs 'orders-demo-runtime-error.log')
    Write-Output ('Read-only demo launcher PID ' + $taskProcess.Id + '; verify /health on port 8001 before starting frontend.')
} finally {
    foreach ($taskName in $taskNames) { [Environment]::SetEnvironmentVariable($taskName,$taskPrevious[$taskName],'Process') }
    if ($null -ne $taskDecrypted) { [Array]::Clear($taskDecrypted,0,$taskDecrypted.Length) }
    $taskPassword = $null
}
