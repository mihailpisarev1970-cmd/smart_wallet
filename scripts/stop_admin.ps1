# Stop the Django admin started by scripts/run_admin.ps1 (ASCII only).
#   powershell -File scripts/stop_admin.ps1

$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".report\admin_pid.txt"

if (-not (Test-Path $pidFile)) {
    Write-Host "Admin is not running (no pid file)"
    exit 0
}

$adminPid = (Get-Content $pidFile -Raw).Trim()
$proc = $null
if ($adminPid) {
    $proc = Get-Process -Id $adminPid -ErrorAction SilentlyContinue
}

if ($proc) {
    Stop-Process -Id $adminPid -Force
    Write-Host ("Admin stopped, pid=" + $adminPid) -ForegroundColor Green
}
else {
    Write-Host ("Process " + $adminPid + " is not running")
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
