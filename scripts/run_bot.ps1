# Start the bot in background (ASCII only to avoid encoding problems).
#   powershell -File scripts/run_bot.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$reportDir = Join-Path $root ".report"
$pidFile = Join-Path $reportDir "bot_pid.txt"

if (-not (Test-Path $python)) {
    Write-Host ("Python not found: " + $python) -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

if (Test-Path $pidFile) {
    $old = (Get-Content $pidFile -Raw).Trim()
    if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) {
        Write-Host ("Bot already running, pid=" + $old) -ForegroundColor Yellow
        exit 0
    }
}

$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = $root

$proc = Start-Process -FilePath $python `
    -ArgumentList "-m", "bot.main" `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput (Join-Path $reportDir "bot_stdout.txt") `
    -RedirectStandardError (Join-Path $reportDir "bot_stderr.txt")

$proc.Id | Out-File -Encoding UTF8 $pidFile
Start-Sleep -Seconds 6

if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
    Write-Host ("Bot started, pid=" + $proc.Id) -ForegroundColor Green
    Write-Host "Logs: logs\bot.log"
}
else {
    Write-Host "Bot process exited. See .report\bot_stderr.txt" -ForegroundColor Red
    Get-Content (Join-Path $reportDir "bot_stderr.txt") -Tail 40
}
