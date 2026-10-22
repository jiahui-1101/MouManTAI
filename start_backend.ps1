param (
    [string]$ColabUrl = ""
)

$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

$envFile = Join-Path $RepoRoot ".env"

# If user provided a new Colab URL as argument, update .env
if ($ColabUrl -ne "") {
    Write-Host "[P1 Launcher] Updating Colab endpoint URL to: $ColabUrl" -ForegroundColor Cyan
    if (Test-Path $envFile) {
        $content = Get-Content $envFile -Raw
        if ($content -match "P1_AI_ENDPOINT_URL=") {
            $content = $content -replace "P1_AI_ENDPOINT_URL=.*", "P1_AI_ENDPOINT_URL=$ColabUrl"
        } else {
            $content += "`nP1_AI_ENDPOINT_URL=$ColabUrl`n"
        }
        Set-Content -Path $envFile -Value $content -Encoding utf8
    } else {
        Set-Content -Path $envFile -Value @"
P1_AI_ENABLED=false
P1_AI_ENDPOINT_MODE=direct
P1_AI_ENDPOINT_URL=$ColabUrl
P1_AI_API_KEY=
P1_DATABASE_URL=REPLACE_WITH_PRIVATE_P1_DATABASE_URL
PYTHONPATH=backend
"@ -Encoding utf8
    }
}

# If .env does not exist, initialize it
if (-not (Test-Path $envFile)) {
    Write-Host "[P1 Launcher] Initializing default .env file..." -ForegroundColor Yellow
    Set-Content -Path $envFile -Value @"
P1_AI_ENABLED=false
P1_AI_ENDPOINT_MODE=direct
P1_AI_ENDPOINT_URL=
P1_AI_API_KEY=
P1_DATABASE_URL=REPLACE_WITH_PRIVATE_P1_DATABASE_URL
PYTHONPATH=backend
"@ -Encoding utf8
}

# Load .env into current PowerShell session
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $parts = $line.Split("=", 2)
        $k = $parts[0].Trim()
        $v = $parts[1].Trim().Trim('"').Trim("'")
        [System.Environment]::SetEnvironmentVariable($k, $v, "Process")
    }
}

# Ensure database URL and pythonpath exist
if (-not [System.Environment]::GetEnvironmentVariable("P1_DATABASE_URL", "Process")) {
    [System.Environment]::SetEnvironmentVariable("P1_DATABASE_URL", "REPLACE_WITH_PRIVATE_P1_DATABASE_URL", "Process")
}
if (-not [System.Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")) {
    [System.Environment]::SetEnvironmentVariable("PYTHONPATH", "backend", "Process")
}

$activeUrl = [System.Environment]::GetEnvironmentVariable("P1_AI_ENDPOINT_URL", "Process")
if ($env:P1_DATABASE_URL -eq 'REPLACE_WITH_PRIVATE_P1_DATABASE_URL') {
    throw 'Configure P1_DATABASE_URL privately before starting.'
}
if ($activeUrl -match '/dev/p1/infer/?$') {
    $env:P1_AI_ENABLED = 'false'
    $activeUrl = ''
    Write-Host '[P1] Retired simulated endpoint disabled. Deterministic rules only.'
}

# Test if remote Colab endpoint is alive; if offline, auto-switch to built-in local engine
$usingColab = $false
if ($activeUrl -and $activeUrl.StartsWith("https://")) {
    try {
        $healthUrl = $activeUrl.Replace("/infer", "/health")
        $resp = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 3 -ErrorAction Stop
        if ($resp.status -in @("ready", "reachable")) {
            $usingColab = $true
            Write-Host "[P1 Launcher] Remote Colab GPU is ONLINE ($($resp.device))!" -ForegroundColor Green
        }
    } catch {
        Write-Host "[P1 Launcher] Endpoint unavailable. Deterministic rules remain available; no simulated model fallback." -ForegroundColor Yellow
    }
} elseif (-not $activeUrl) {
    [System.Environment]::SetEnvironmentVariable("P1_AI_ENABLED", "false", "Process")
}

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  MouManTAI P1 Full-Stack Launcher" -ForegroundColor Green
Write-Host "  P1_AI_ENABLED:       $([System.Environment]::GetEnvironmentVariable('P1_AI_ENABLED', 'Process'))" -ForegroundColor White
Write-Host "  P1_AI_ENDPOINT_MODE: $([System.Environment]::GetEnvironmentVariable('P1_AI_ENDPOINT_MODE', 'Process'))" -ForegroundColor White
Write-Host "  P1_AI_ENDPOINT_URL:  $activeUrl" -ForegroundColor White
if ($usingColab) {
    Write-Host "  AI Engine:           Remote reachable; device requires per-inference telemetry" -ForegroundColor Cyan
} else {
    Write-Host "  AI Engine:           Optional endpoint; no successful inference implied" -ForegroundColor Cyan
}
Write-Host "==========================================================" -ForegroundColor Green

$pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

# Auto-open browser after 2 seconds in background
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process "http://localhost:5173/inbox"
} | Out-Null

& $pythonExe -m uvicorn app.context.dev_app:app --port 8000 --reload
