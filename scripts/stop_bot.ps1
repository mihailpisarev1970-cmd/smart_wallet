# Stop the bot started by scripts/run_bot.ps1 (ASCII only).
#   powershell -File scripts/stop_bot.ps1

$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".report\bot_pid.txt"

if (-not (Test-Path $pidFile)) {
    Write-Host "Bot is not running (no pid file)"
    exit 0
}

$botPid = (Get-Content $pidFile -Raw).Trim()
$proc = $null
if ($botPid) {
    $proc = Get-Process -Id $botPid -ErrorAction SilentlyContinue
}

if ($proc) {
    Stop-Process -Id $botPid -Force
    Write-Host ("Bot stopped, pid=" + $botPid) -ForegroundColor Green
}
else {
    Write-Host ("Process " + $botPid + " is not running")
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
