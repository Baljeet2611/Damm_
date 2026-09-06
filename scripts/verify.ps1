# ==============================================================================
# Dam Break Decision Support System - Verification Script
# ==============================================================================
# Executes full test suite and frontend production build.
# Returns exit code 0 on complete pass, 1 on failure.
# ==============================================================================

$ErrorActionPreference = "Continue"
$workspaceRoot = (Resolve-Path "$PSScriptRoot/..").Path
$backendDir = Join-Path $workspaceRoot "backend"
$frontendDir = Join-Path $workspaceRoot "frontend"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   SIH Dam Break DSS - Full System Verification Audit" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Workspace Root: $workspaceRoot" -ForegroundColor DarkGray
Write-Host "Timestamp:      $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor DarkGray
Write-Host ""

# 1. Locate Python Interpreter
$pythonExe = "python"
$miniforgePath = "$env:USERPROFILE\miniforge3\envs\sih-app\python.exe"
if (Test-Path $miniforgePath) {
    $pythonExe = $miniforgePath
}

Write-Host "1. Testing Backend (FastAPI, Schemas, Rasters, Scenarios, SPH, GEE)..." -ForegroundColor Yellow
$testStart = Get-Date
Push-Location $backendDir
& $pythonExe -m pytest -v
$backendExit = $LASTEXITCODE
Pop-Location
$testDuration = ((Get-Date) - $testStart).TotalSeconds

if ($backendExit -eq 0) {
    Write-Host "   [PASS] Backend test suite passed in $([math]::Round($testDuration, 2))s" -ForegroundColor Green
} else {
    Write-Host "   [FAIL] Backend test suite failed (Exit code: $backendExit)" -ForegroundColor Red
}

Write-Host ""
Write-Host "2. Building Frontend Production Bundle (Vite + TypeScript)..." -ForegroundColor Yellow
$buildStart = Get-Date
Push-Location $frontendDir
& npm run build
$frontendExit = $LASTEXITCODE
Pop-Location
$buildDuration = ((Get-Date) - $buildStart).TotalSeconds

if ($frontendExit -eq 0) {
    Write-Host "   [PASS] Frontend production build succeeded in $([math]::Round($buildDuration, 2))s" -ForegroundColor Green
} else {
    Write-Host "   [FAIL] Frontend build failed (Exit code: $frontendExit)" -ForegroundColor Red
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Verification Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Backend Pytest Suite: " -NoNewline
if ($backendExit -eq 0) { Write-Host "PASSED" -ForegroundColor Green } else { Write-Host "FAILED" -ForegroundColor Red }

Write-Host "Frontend Production:  " -NoNewline
if ($frontendExit -eq 0) { Write-Host "PASSED" -ForegroundColor Green } else { Write-Host "FAILED" -ForegroundColor Red }

if ($backendExit -eq 0 -and $frontendExit -eq 0) {
    Write-Host ""
    Write-Host ">>> ALL SYSTEMS OPERATIONAL AND VERIFIED (Exit Code 0) <<<" -ForegroundColor Green
    exit 0
} else {
    Write-Host ""
    Write-Host ">>> VERIFICATION FAILED (Exit Code 1) <<<" -ForegroundColor Red
    exit 1
}
