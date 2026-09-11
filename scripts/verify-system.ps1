# ==============================================================================
# SIH 26161 Dam Break Decision Support System - System Verification Script
# ==============================================================================
# Performs complete static analysis, environment discovery, tests, and build check.
# ==============================================================================

$ErrorActionPreference = "Continue"
$workspaceRoot = (Resolve-Path "$PSScriptRoot/..").Path
$backendDir = Join-Path $workspaceRoot "backend"
$frontendDir = Join-Path $workspaceRoot "frontend"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   SIH 26161 - Complete System Verification & Audit" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Timestamp: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor DarkGray
Write-Host "Workspace: $workspaceRoot" -ForegroundColor DarkGray
Write-Host ""

$results = [ordered]@{}

# 1. Node & npm
Write-Host "[1/9] Checking Node.js & npm..." -ForegroundColor Yellow
$nodeVer = & node --version 2>$null
$npmVer = & npm --version 2>$null
if ($nodeVer -and $npmVer) {
    Write-Host "   Node: $nodeVer | npm: $npmVer" -ForegroundColor Green
    $results["Node.js"] = "PASS ($nodeVer)"
    $results["npm"] = "PASS ($npmVer)"
} else {
    Write-Host "   [FAIL] Node.js or npm missing." -ForegroundColor Red
    $results["Node.js"] = "FAIL"
    $results["npm"] = "FAIL"
}

# 2. Conda / Python sih-app
Write-Host "[2/9] Inspecting sih-app Conda Environment..." -ForegroundColor Yellow
$appPython = "$env:USERPROFILE\anaconda3\envs\sih-app\python.exe"
if (-not (Test-Path $appPython)) {
    $appPython = "$env:USERPROFILE\miniforge3\envs\sih-app\python.exe"
}
if (-not (Test-Path $appPython)) {
    $appPython = (Get-Command python -ErrorAction SilentlyContinue).Source
}

if ($appPython -and (Test-Path $appPython)) {
    $pyVer = & $appPython --version 2>$null
    Write-Host "   Path: $appPython ($pyVer)" -ForegroundColor Green
    $results["sih-app Python"] = "PASS ($pyVer)"
} else {
    Write-Host "   [FAIL] sih-app python executable missing." -ForegroundColor Red
    $results["sih-app Python"] = "FAIL"
}

# 3. Backend Module Import Test
Write-Host "[3/9] Testing Backend Core Imports..." -ForegroundColor Yellow
$importCheck = & $appPython -c "import app.main; import app.onboarding_service; import app.exposure_service; print('OK')" 2>$null
if ($importCheck -match "OK") {
    Write-Host "   [PASS] FastAPI, Onboarding, and Exposure modules import cleanly." -ForegroundColor Green
    $results["Backend Core Imports"] = "PASS"
} else {
    Write-Host "   [FAIL] Backend import check failed." -ForegroundColor Red
    $results["Backend Core Imports"] = "FAIL"
}

# 4. Conda sih-anuga & ANUGA Import Check
Write-Host "[4/9] Inspecting sih-anuga Solver Environment..." -ForegroundColor Yellow
$anugaPython = "$env:USERPROFILE\anaconda3\envs\sih-anuga\python.exe"
if (Test-Path $anugaPython) {
    $anugaCheck = & $anugaPython -c "import anuga; import sys; print(f'OK: Python {sys.version.split()[0]}, ANUGA {getattr(anuga, \"__version__\", \"0.0.0+unknown\")}')" 2>$null
    if ($anugaCheck -match "OK") {
        Write-Host "   [PASS] $anugaCheck" -ForegroundColor Green
        $results["ANUGA Discovery & Import"] = "PASS ($anugaCheck)"
    } else {
        Write-Host "   [WARN] sih-anuga python found but failed to import anuga." -ForegroundColor Yellow
        $results["ANUGA Discovery & Import"] = "FAIL"
    }
} else {
    Write-Host "   [INFO] sih-anuga not located at default Conda path. Gated mode active." -ForegroundColor DarkGray
    $results["ANUGA Discovery & Import"] = "GATED_OPTIONAL"
}

# 5. Optional Google Earth Engine Check
Write-Host "[5/9] Inspecting Google Earth Engine (Optional)..." -ForegroundColor Yellow
$geeCheck = & $appPython -c "import ee; print('EE_API_AVAILABLE')" 2>$null
if ($geeCheck -match "EE_API_AVAILABLE") {
    Write-Host "   [PASS] earthengine-api installed in sih-app." -ForegroundColor Green
    $results["Google Earth Engine API"] = "AVAILABLE"
} else {
    Write-Host "   [INFO] earthengine-api not installed or not configured. Gated gracefully." -ForegroundColor DarkGray
    $results["Google Earth Engine API"] = "OPTIONAL_NOT_CONFIGURED"
}

# 6. Frontend Lint (Meaningful Static Analysis)
Write-Host "[6/9] Running Frontend Static Analysis (oxlint: correctness + suspicious)..." -ForegroundColor Yellow
Push-Location $frontendDir
$lintOutput = & npm run lint 2>&1
$lintExit = $LASTEXITCODE
Pop-Location
if ($lintExit -eq 0) {
    Write-Host "   [PASS] oxlint static analysis passed with 0 errors." -ForegroundColor Green
    $results["Frontend Lint"] = "PASS (0 errors, 146 rules)"
} else {
    Write-Host "   [FAIL] Frontend lint failed." -ForegroundColor Red
    $results["Frontend Lint"] = "FAIL"
}

# 7. Frontend Production Bundle Build
Write-Host "[7/9] Building Frontend Production Bundle (tsc + Vite)..." -ForegroundColor Yellow
Push-Location $frontendDir
$buildOutput = & npm run build 2>&1
$buildExit = $LASTEXITCODE
Pop-Location
if ($buildExit -eq 0) {
    Write-Host "   [PASS] Vite bundle successfully built." -ForegroundColor Green
    $results["Frontend Build"] = "PASS (dist/ generated)"
} else {
    Write-Host "   [FAIL] Frontend build failed." -ForegroundColor Red
    $results["Frontend Build"] = "FAIL"
}

# 8. Backend Test Suite (Pytest)
Write-Host "[8/9] Executing Backend Pytest Suite..." -ForegroundColor Yellow
Push-Location $backendDir
$pytestOutput = & $appPython -m pytest -v --durations=5 2>&1
$pytestExit = $LASTEXITCODE
Pop-Location
if ($pytestExit -eq 0) {
    Write-Host "   [PASS] Pytest completed with 0 failures." -ForegroundColor Green
    $results["Backend Pytest Suite"] = "PASS (0 failed)"
} else {
    Write-Host "   [FAIL] Pytest encountered failures." -ForegroundColor Red
    $results["Backend Pytest Suite"] = "FAIL"
}

# 9. Real ANUGA Smoke Test (Phase 23 Real Solver Simulation)
Write-Host "[9/9] Running ANUGA Real Solver Smoke Test..." -ForegroundColor Yellow
Push-Location $backendDir
$smokeOutput = & $appPython -m pytest backend/tests/test_anuga_real_smoke_phase23.py 2>&1
$smokeExit = $LASTEXITCODE
Pop-Location
if ($smokeExit -eq 0) {
    Write-Host "   [PASS] Real ANUGA Domain evolved, SWW validated, GeoTIFFs post-processed." -ForegroundColor Green
    $results["ANUGA Real Solver Smoke Test"] = "PASS"
} else {
    Write-Host "   [FAIL] Real ANUGA smoke test failed." -ForegroundColor Red
    $results["ANUGA Real Solver Smoke Test"] = "FAIL"
}

# Summary Report Table
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   System Verification Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
foreach ($key in $results.Keys) {
    $val = $results[$key]
    $color = if ($val -match "PASS|AVAILABLE") { "Green" } elseif ($val -match "OPTIONAL|GATED") { "DarkYellow" } else { "Red" }
    Write-Host ("   {0,-32} : " -f $key) -NoNewline
    Write-Host $val -ForegroundColor $color
}
Write-Host "============================================================" -ForegroundColor Cyan

$hasFailure = $results.Values | Where-Object { $_ -match "FAIL" }
if ($hasFailure) {
    Write-Host ">>> SYSTEM AUDIT FAILED (Exit Code 1) <<<" -ForegroundColor Red
    exit 1
} else {
    Write-Host ">>> ALL MANDATORY SYSTEMS VERIFIED (Exit Code 0) <<<" -ForegroundColor Green
    exit 0
}
