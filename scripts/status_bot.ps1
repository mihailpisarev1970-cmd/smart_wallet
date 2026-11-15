# Bot status checker (ASCII only to avoid encoding problems).
#   powershell -File scripts/status_bot.ps1

$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".report\bot_pid.txt"
$logFile = Join-Path $root "logs\bot.log"

Write-Host "=== Bot status ===" -ForegroundColor Cyan

$running = $false
if (Test-Path $pidFile) {
    $botPid = (Get-Content $pidFile -Raw).Trim()
    if ($botPid) {
        $proc = Get-Process -Id $botPid -ErrorAction SilentlyContinue
        if ($proc) {
            $running = $true
            Write-Host ("RUNNING  pid=" + $botPid + "  started=" + $proc.StartTime) -ForegroundColor Green
        }
    }
}
if (-not $running) {
    Write-Host "NOT RUNNING. Start it with: powershell -File scripts/run_bot.ps1" -ForegroundColor Yellow
}

if (Test-Path $logFile) {
    Write-Host ""
    Write-Host "=== Last log lines ===" -ForegroundColor Cyan
    Get-Content $logFile -Tail 20 -Encoding UTF8
}
