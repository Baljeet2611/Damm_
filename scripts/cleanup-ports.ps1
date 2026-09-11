Write-Host "=== 1. Stopping process on Port 8000 ==="
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
ForEach-Object { 
    Write-Host "Stopping process PID $($_.OwningProcess) on port 8000"
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue 
}

Write-Host "=== 2. Stopping process on Port 5173 ==="
Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue |
ForEach-Object { 
    Write-Host "Stopping process PID $($_.OwningProcess) on port 5173"
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue 
}

Write-Host "=== 3. Checking project-related ANUGA/Python processes ==="
$procs = Get-CimInstance Win32_Process |
Where-Object {
    $_.CommandLine -like "*Damm_*" -or
    $_.CommandLine -like "*sih-anuga*"
} |
Select-Object ProcessId, Name, CommandLine

if ($procs) {
    Write-Host "Found matching processes:"
    $procs | Format-Table -Property ProcessId, Name
    
    Write-Host "Stopping matching processes..."
    Get-CimInstance Win32_Process |
    Where-Object {
        ($_.CommandLine -like "*Damm_*" -or $_.CommandLine -like "*sih-anuga*") -and
        $_.ProcessId -ne $PID
    } |
    ForEach-Object {
        Write-Host "Stopping PID $($_.ProcessId) ($($_.Name))"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "No stray Damm_ or sih-anuga processes found."
}

Start-Sleep -Seconds 2

Write-Host "=== 4. Confirming ports 8000 & 5173 are free ==="
$connections = Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue
if ($connections) {
    Write-Host "[WARNING] Ports still occupied:" -ForegroundColor Red
    $connections | Format-Table -Property LocalAddress, LocalPort, State, OwningProcess
} else {
    Write-Host "Ports 8000 and 5173 are verified completely FREE." -ForegroundColor Green
}
