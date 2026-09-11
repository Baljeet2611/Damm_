# ==============================================================================
# SIH 26161 Dam Break Decision Support System - Safe Startup Script
# ==============================================================================
# Checks prerequisites, inspects ports, and safely launches FastAPI and Vite
# ==============================================================================

$ErrorActionPreference = "Continue"
$workspaceRoot = (Resolve-Path "$PSScriptRoot/..").Path
$backendDir = Join-Path $workspaceRoot "backend"
$frontendDir = Join-Path $workspaceRoot "frontend"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   SIH 26161 Dam Break DSS - Safe Startup Manager" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Inspect Node & npm
Write-Host "[1/5] Checking Node.js & npm..." -ForegroundColor Yellow
$nodeVer = & node --version 2>$null
$npmVer = & npm --version 2>$null
if ($nodeVer -and $npmVer) {
    Write-Host "   Node: $nodeVer | npm: $npmVer" -ForegroundColor Green
} else {
    Write-Host "   [ERROR] Node.js or npm is not in PATH. Please install Node.js 18+." -ForegroundColor Red
    exit 1
}

# 2. Inspect Conda / Python Environments
Write-Host "[2/5] Inspecting Python Environments..." -ForegroundColor Yellow
$appPython = "$env:USERPROFILE\anaconda3\envs\sih-app\python.exe"
if (-not (Test-Path $appPython)) {
    $appPython = "$env:USERPROFILE\miniforge3\envs\sih-app\python.exe"
}
if (-not (Test-Path $appPython)) {
    $appPython = (Get-Command python -ErrorAction SilentlyContinue).Source
}

if ($appPython -and (Test-Path $appPython)) {
    $pyVer = & $appPython --version 2>$null
    Write-Host "   sih-app Python: $appPython ($pyVer)" -ForegroundColor Green
} else {
    Write-Host "   [ERROR] Could not find sih-app environment. Please create conda env 'sih-app'." -ForegroundColor Red
    exit 1
}

# ANUGA check
$anugaPython = $env:ANUGA_PYTHON_EXECUTABLE
if (-not $anugaPython -or -not (Test-Path $anugaPython)) {
    $anugaPython = "$env:USERPROFILE\anaconda3\envs\sih-anuga\python.exe"
}
if (Test-Path $anugaPython) {
    $anugaCheck = & $anugaPython -c "import anuga; print('ANUGA ' + getattr(anuga, '__version__', 'detected'))" 2>$null
    Write-Host "   sih-anuga: $anugaCheck (Found solver environment)" -ForegroundColor Green
} else {
    Write-Host "   sih-anuga: Not installed at default location (Simulation runner will run in gated mode)" -ForegroundColor DarkGray
}

# 3. Inspect Ports
Write-Host "[3/5] Inspecting network ports (8000, 5173)..." -ForegroundColor Yellow
$port8000Proc = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
$port5173Proc = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique

$backendAlreadyRunning = $false
if ($port8000Proc) {
    Write-Host "   Port 8000 is currently occupied by PID $port8000Proc." -ForegroundColor Yellow
    # Check if it responds as our FastAPI
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/system/health-summary" -TimeoutSec 2 -ErrorAction Stop
        if ($resp.overall_status) {
            Write-Host "   -> FastAPI Dam DSS Backend is ALREADY running and healthy." -ForegroundColor Green
            $backendAlreadyRunning = $true
        }
    } catch {
        Write-Host "   [WARNING] Port 8000 occupied by another service or unresponsive backend. Please free port 8000." -ForegroundColor Red
    }
}

$frontendAlreadyRunning = $false
if ($port5173Proc) {
    Write-Host "   Port 5173 is currently occupied by PID $port5173Proc." -ForegroundColor Yellow
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -TimeoutSec 2 -ErrorAction Stop -UseBasicParsing
        if ($resp.StatusCode -eq 200) {
            Write-Host "   -> Vite Frontend dev server is ALREADY running." -ForegroundColor Green
            $frontendAlreadyRunning = $true
        }
    } catch {
        Write-Host "   [WARNING] Port 5173 occupied by another process. Please free port 5173." -ForegroundColor Red
    }
}

# 4. Start Services if not already running
Write-Host "[4/5] Launching services..." -ForegroundColor Yellow
if (-not $backendAlreadyRunning) {
    Write-Host "   Starting FastAPI backend on port 8000..." -ForegroundColor Cyan
    $envArgs = ""
    if ($env:ENABLE_CUSTOM_ANUGA_EXECUTION) { $envArgs += "`$env:ENABLE_CUSTOM_ANUGA_EXECUTION='$env:ENABLE_CUSTOM_ANUGA_EXECUTION'; " }
    if ($env:ANUGA_PYTHON_EXECUTABLE) { $envArgs += "`$env:ANUGA_PYTHON_EXECUTABLE='$env:ANUGA_PYTHON_EXECUTABLE'; " }
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "$envArgs Set-Location '$backendDir'; & '$appPython' -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
} else {
    Write-Host "   Skipping backend launch (already active)." -ForegroundColor DarkGray
}

if (-not $frontendAlreadyRunning) {
    Write-Host "   Starting Vite frontend on port 5173..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$frontendDir'; npm run dev -- --host 127.0.0.1 --port 5173"
} else {
    Write-Host "   Skipping frontend launch (already active)." -ForegroundColor DarkGray
}

# 5. Ready Summary
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   SIH Dam Break Decision Support System Ready" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Frontend Application: http://127.0.0.1:5173" -ForegroundColor White
Write-Host "   Backend API Docs:     http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "   System Health HUD:    http://127.0.0.1:8000/api/system/health-summary" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
