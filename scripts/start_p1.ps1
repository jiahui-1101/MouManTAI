# PowerShell helper script to start P1 development environment
param(
    [string]$AiEndpointUrl = "",
    [string]$AiApiKey = "dev-token",
    [string]$AiEndpointMode = "direct"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$env:PYTHONPATH = "backend"
$env:P1_DATABASE_URL = "postgresql+psycopg://p1_local:d7ff8ea1c01a68bd3c5107338b375d1259a4693f2d7716c0@127.0.0.1:55432/monmantai_p1"

if ($AiEndpointUrl -ne "") {
    $env:P1_AI_ENABLED = "true"
    $env:P1_AI_ENDPOINT_URL = $AiEndpointUrl
    $env:P1_AI_API_KEY = $AiApiKey
    $env:P1_AI_ENDPOINT_MODE = $AiEndpointMode
    Write-Host "[P1] AI inference enabled -> URL: $AiEndpointUrl (Mode: $AiEndpointMode)" -ForegroundColor Cyan
} else {
    Write-Host "[P1] AI endpoint not specified; operating with deterministic L0 rules and honest fallback." -ForegroundColor Yellow
}

Write-Host "[P1] Starting FastAPI development server at http://127.0.0.1:8000 ..." -ForegroundColor Green
& ".\.venv\Scripts\python.exe" -m uvicorn app.context.dev_app:app --host 127.0.0.1 --port 8000 --reload
