# ==============================================================================
# Dam Break Decision Support System - One-Command Demo Launcher
# ==============================================================================
# Verifies environment, checks prerequisites, starts backend & frontend
# services safely, verifies health, and opens the local interactive dashboard.
# ==============================================================================

$ErrorActionPreference = "Continue"
$workspaceRoot = (Resolve-Path "$PSScriptRoot/..").Path
$backendDir = Join-Path $workspaceRoot "backend"
$frontendDir = Join-Path $workspaceRoot "frontend"
$dataDir = Join-Path $workspaceRoot "data\raw\data_hidkal"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   SIH Dam Break Decision Support System - Live Demo Launcher" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Workspace: $workspaceRoot" -ForegroundColor DarkGray
Write-Host ""

# 1. Verify Prerequisites & Local Raw Datasets
Write-Host "1. Checking Local Prerequisite Datasets..." -ForegroundColor Yellow
$requiredFiles = @(
    "hidkal_dem.tif",
    "hidkal_depth.tif",
    "hidkal_velocity.tif",
    "hidkal_arrival.tif",
    "hidkal_assets.geojson",
    "hidkal_roads.graphml"
)

$missingFiles = @()
foreach ($file in $requiredFiles) {
    $filePath = Join-Path $dataDir $file
    if (-not (Test-Path $filePath)) {
        $missingFiles += $file
    }
}

if ($missingFiles.Count -gt 0) {
    Write-Host "   [ERROR] Missing required dataset files in ${dataDir}:" -ForegroundColor Red
    foreach ($m in $missingFiles) {
        Write-Host "     - $m" -ForegroundColor Red
    }
    Write-Host "   Please extract data_hidkal.zip into data/raw/ before running demo." -ForegroundColor Red
    exit 1
} else {
    Write-Host "   [OK] All 6 local Hidkal domain files verified." -ForegroundColor Green
}

# 2. Locate Python & Node Executables
Write-Host ""
Write-Host "2. Verifying Python and Node Environments..." -ForegroundColor Yellow
$pythonExe = "python"
$miniforgePath = "$env:USERPROFILE\miniforge3\envs\sih-app\python.exe"
if (Test-Path $miniforgePath) {
    $pythonExe = $miniforgePath
}
Write-Host "   Using Python: $pythonExe" -ForegroundColor DarkGray

$nodeVer = & node -v 2>$null
if (-not $nodeVer) {
    Write-Host "   [ERROR] Node.js is not found in PATH. Please install Node.js." -ForegroundColor Red
    exit 1
}
Write-Host "   Using Node:   $nodeVer" -ForegroundColor DarkGray

# 3. Check Port Availability / Existing Services
Write-Host ""
Write-Host "3. Detecting Service Status..." -ForegroundColor Yellow

$backendHealthy = $false
try {
    $res = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -Method Get -TimeoutSec 2 -ErrorAction Stop
    if ($res.status -eq "ok") {
        $backendHealthy = $true
        Write-Host "   [OK] Backend API is already running and healthy on port 8000." -ForegroundColor Green
    }
} catch {
    $backendHealthy = $false
}

if (-not $backendHealthy) {
    Write-Host "   Starting FastAPI backend on http://127.0.0.1:8000..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "& '$pythonExe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000" -WorkingDirectory $backendDir
    
    # Wait for backend health
    $retries = 15
    while ($retries -gt 0) {
        Start-Sleep -Seconds 1
        try {
            $res = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -Method Get -TimeoutSec 2 -ErrorAction Stop
            if ($res.status -eq "ok") {
                $backendHealthy = $true
                break
            }
        } catch {}
        $retries--
    }
    
    if ($backendHealthy) {
        Write-Host "   [OK] Backend started successfully." -ForegroundColor Green
    } else {
        Write-Host "   [WARN] Backend did not respond to health check within timeout. Proceeding..." -ForegroundColor Yellow
    }
}

$frontendHealthy = $false
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect("127.0.0.1", 5173)
    $frontendHealthy = $true
    $tcp.Close()
    Write-Host "   [OK] Frontend dev server is already listening on port 5173." -ForegroundColor Green
} catch {
    $frontendHealthy = $false
}

if (-not $frontendHealthy) {
    Write-Host "   Starting Vite frontend on http://127.0.0.1:5173..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "npm run dev -- --host 127.0.0.1 --port 5173" -WorkingDirectory $frontendDir
    Start-Sleep -Seconds 3
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Demo Services Ready!" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   - Interactive Web Dashboard: http://localhost:5173" -ForegroundColor White
Write-Host "   - Backend Health Check:      http://127.0.0.1:8000/api/health" -ForegroundColor DarkGray
Write-Host "   - Interactive OpenAPI Docs:  http://127.0.0.1:8000/docs" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Opening web browser..." -ForegroundColor Cyan
Start-Process "http://localhost:5173"

Write-Host ""
Write-Host "------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "HOW TO STOP DEMO SERVICES:" -ForegroundColor Yellow
Write-Host "1. Close the launched backend/frontend PowerShell terminal windows."
Write-Host "2. Or terminate uvicorn / vite dev processes from Task Manager."
Write-Host "------------------------------------------------------------" -ForegroundColor DarkGray
