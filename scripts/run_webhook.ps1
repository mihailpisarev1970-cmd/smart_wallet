# Start the webhook server (MAX events + Robokassa) in background (ASCII only).
#   powershell -File scripts/run_webhook.ps1
# Endpoints: /webhook/max/<secret>  /healthz  /robokassa/{result,success,fail}

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$reportDir = Join-Path $root ".report"
$pidFile = Join-Path $reportDir "webhook_pid.txt"

if (-not (Test-Path $python)) {
    Write-Host ("Python not found: " + $python) -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

if (Test-Path $pidFile) {
    $old = (Get-Content $pidFile -Raw).Trim()
    if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) {
        Write-Host ("Webhook server already running, pid=" + $old) -ForegroundColor Yellow
        exit 0
    }
}

$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = $root

$proc = Start-Process -FilePath $python `
    -ArgumentList "-m", "bot.webhook_server" `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput (Join-Path $reportDir "webhook_stdout.txt") `
    -RedirectStandardError (Join-Path $reportDir "webhook_stderr.txt")

$proc.Id | Out-File -Encoding UTF8 $pidFile
Start-Sleep -Seconds 5

if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
    Write-Host ("Webhook server started, pid=" + $proc.Id) -ForegroundColor Green
    Write-Host "Endpoints: /webhook/max/<secret>, /healthz, /robokassa/*"
}
else {
    Write-Host "Webhook server exited. See .report\webhook_stderr.txt" -ForegroundColor Red
    Get-Content (Join-Path $reportDir "webhook_stderr.txt") -Tail 30
}
