# Development startup script for SIH Dam Break Decision Support System
# Launches FastAPI backend and Vite frontend in separate PowerShell windows

Write-Host "Starting Dam Break DSS Development Servers..." -ForegroundColor Cyan

$workspaceRoot = Resolve-Path "$PSScriptRoot/.."
$backendPath = Join-Path $workspaceRoot "backend"
$frontendPath = Join-Path $workspaceRoot "frontend"

Write-Host "Starting Backend on http://localhost:8000..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "conda activate sih-app; Set-Location '$backendPath'; uvicorn app.main:app --reload --port 8000"

Write-Host "Starting Frontend on http://localhost:5173..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$frontendPath'; npm run dev"

Write-Host "Services started!" -ForegroundColor Green
Write-Host "- Backend API: http://localhost:8000/api/health"
Write-Host "- Swagger Docs: http://localhost:8000/docs"
Write-Host "- Frontend UI: http://localhost:5173"
