param (
    [string]$ColabUrl = ""
)

$envFile = Join-Path $PSScriptRoot ".env"

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
P1_AI_ENABLED=true
P1_AI_ENDPOINT_MODE=direct
P1_AI_ENDPOINT_URL=$ColabUrl
P1_AI_API_KEY=p1-colab-secret
"@ -Encoding utf8
    }
}

# If .env does not exist, initialize it
if (-not (Test-Path $envFile)) {
    Write-Host "[P1 Launcher] Initializing default .env file..." -ForegroundColor Yellow
    Set-Content -Path $envFile -Value @"
# P1 Context Intelligence AI Proposal Pipeline
P1_AI_ENABLED=true
P1_AI_ENDPOINT_MODE=direct
P1_AI_ENDPOINT_URL=https://your-colab-url.trycloudflare.com/infer
P1_AI_API_KEY=p1-colab-secret
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

$activeUrl = [System.Environment]::GetEnvironmentVariable("P1_AI_ENDPOINT_URL", "Process")
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  MouManTAI P1 Backend Launcher" -ForegroundColor Green
Write-Host "  P1_AI_ENABLED:       $([System.Environment]::GetEnvironmentVariable('P1_AI_ENABLED', 'Process'))" -ForegroundColor White
Write-Host "  P1_AI_ENDPOINT_MODE: $([System.Environment]::GetEnvironmentVariable('P1_AI_ENDPOINT_MODE', 'Process'))" -ForegroundColor White
Write-Host "  P1_AI_ENDPOINT_URL:  $activeUrl" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green

$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

& $pythonExe -m uvicorn app.context.dev_app:app --port 8000 --reload
