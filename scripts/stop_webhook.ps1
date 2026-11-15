# Stop the webhook server (ASCII only).
#   powershell -File scripts/stop_webhook.ps1

$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".report\webhook_pid.txt"

if (-not (Test-Path $pidFile)) {
    Write-Host "Webhook server is not running (no pid file)"
    exit 0
}

$serverPid = (Get-Content $pidFile -Raw).Trim()
$proc = $null
if ($serverPid) {
    $proc = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
}

if ($proc) {
    Stop-Process -Id $serverPid -Force
    Write-Host ("Webhook server stopped, pid=" + $serverPid) -ForegroundColor Green
}
else {
    Write-Host ("Process " + $serverPid + " is not running")
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
