# ==============================================================================
# SIH 26161 - Real ANUGA Engineering Solver Smoke Test Runner
# ==============================================================================

$ErrorActionPreference = "Continue"
$workspaceRoot = (Resolve-Path "$PSScriptRoot/..").Path
$appPython = "$env:USERPROFILE\anaconda3\envs\sih-app\python.exe"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Executing Real ANUGA Solver Engineering Smoke Test" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

Push-Location (Join-Path $workspaceRoot "backend")
& $appPython -m pytest tests/test_anuga_real_smoke_phase23.py -v -s
$exitCode = $LASTEXITCODE
Pop-Location

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host ">>> ANUGA REAL SMOKE TEST: PASSED <<<" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host ">>> ANUGA REAL SMOKE TEST: FAILED <<<" -ForegroundColor Red
}
exit $exitCode
