param([ValidateRange(1024,65535)][int]$Port = 5173)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskFrontend = Join-Path $taskRoot 'frontend'
$taskVite = Join-Path $taskFrontend 'node_modules/vite/bin/vite.js'
if (-not (Test-Path -LiteralPath $taskVite)) { throw 'Existing frontend dependencies required; nothing started.' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is occupied. Inspect and stop only the intended frontend before launching."
}
foreach ($taskBackendPort in @(8000,8001)) {
    $taskHealth = Invoke-RestMethod "http://127.0.0.1:$taskBackendPort/health" -TimeoutSec 10
    if ($taskHealth.status -ne 'ok') { throw "Backend $taskBackendPort health check failed; nothing started." }
}
$taskLogs = Join-Path $env:LOCALAPPDATA 'MouManTAI-Demo-UAT'
New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
$taskNames = @('VITE_ORDERS_DEMO','VITE_API_BASE_URL','MOUMANTAI_ISOLATED_E2E','MOUMANTAI_ISOLATED_E2E_KEY')
$taskPrevious = @{}
foreach ($taskName in $taskNames) { $taskPrevious[$taskName] = [Environment]::GetEnvironmentVariable($taskName,'Process') }
try {
    $env:VITE_ORDERS_DEMO = '1'
    # Same-origin reads: Vite sends Orders demo reads to 8001, all other APIs to 8000.
    $env:VITE_API_BASE_URL = ''
    $env:MOUMANTAI_ISOLATED_E2E = '0'
    Remove-Item Env:MOUMANTAI_ISOLATED_E2E_KEY -ErrorAction SilentlyContinue
    $taskNode = (Get-Command node -ErrorAction Stop).Source
    $taskProcess = Start-Process -FilePath $taskNode -ArgumentList @(('"' + $taskVite + '"'),'--mode','demo','--host','127.0.0.1','--port',"$Port",'--strictPort') `
        -WorkingDirectory $taskFrontend -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $taskLogs "orders-frontend-$Port.log") `
        -RedirectStandardError (Join-Path $taskLogs "orders-frontend-$Port-error.log")
    Write-Output "Orders Planning frontend started: PID $($taskProcess.Id), http://localhost:$Port; explicit SYNTHETIC reads only."
} finally {
    foreach ($taskName in $taskNames) { [Environment]::SetEnvironmentVariable($taskName,$taskPrevious[$taskName],'Process') }
}
