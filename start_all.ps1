param (
    [string]$ColabUrl = ""
)

$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       🚀 MouManTAI Full-Stack One-Click Launcher        " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check & start PostgreSQL Docker container if docker is running and DB not reachable
$dbOnline = $false
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect("127.0.0.1", 55432)
    $tcp.Close()
    $dbOnline = $true
    Write-Host "[1/4] PostgreSQL Database is ONLINE (127.0.0.1:55432)" -ForegroundColor Green
} catch {
    Write-Host "[1/4] PostgreSQL not responding on 55432, checking Docker..." -ForegroundColor Yellow
    try {
        docker compose up -d
        Write-Host "      Docker compose started successfully!" -ForegroundColor Green
    } catch {
        Write-Host "      Docker not found or container already running." -ForegroundColor Gray
    }
}

# 2. Check & start Frontend Vite server
$frontendOnline = $false
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:5173" -Method Head -TimeoutSec 2 -ErrorAction Stop
    $frontendOnline = $true
    Write-Host "[2/4] Frontend Vite Server is ONLINE (http://localhost:5173)" -ForegroundColor Green
} catch {
    Write-Host "[2/4] Starting Frontend Vite Server in background..." -ForegroundColor Yellow
    $frontendDir = Join-Path $RepoRoot "frontend"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c cd /d `"$frontendDir`" && npm run dev" -WindowStyle Minimized
    Write-Host "      Frontend launched on http://localhost:5173" -ForegroundColor Green
}

# 3. Check & connect AI Engine / Colab GPU
Write-Host "[3/4] Initializing AI Pipeline & GPU Engine..." -ForegroundColor Cyan

# 4. Delegate to start_backend.ps1 which runs Uvicorn and opens browser
& (Join-Path $RepoRoot "start_backend.ps1") -ColabUrl $ColabUrl
