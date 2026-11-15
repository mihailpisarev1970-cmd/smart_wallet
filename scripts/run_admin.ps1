# Запуск Django-админки в фоне (ASCII only).
#   powershell -File scripts/run_admin.ps1
# Адрес: http://127.0.0.1:8000/admin/dashboard/

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$reportDir = Join-Path $root ".report"
$pidFile = Join-Path $reportDir "admin_pid.txt"

if (-not (Test-Path $python)) {
    Write-Host ("Python not found: " + $python) -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

if (Test-Path $pidFile) {
    $old = (Get-Content $pidFile -Raw).Trim()
    if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) {
        Write-Host ("Admin already running, pid=" + $old) -ForegroundColor Yellow
        exit 0
    }
}

$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = $root

$proc = Start-Process -FilePath $python `
    -ArgumentList "admin_panel\manage.py", "runserver", "127.0.0.1:8000", "--noreload" `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput (Join-Path $reportDir "admin_stdout.txt") `
    -RedirectStandardError (Join-Path $reportDir "admin_stderr.txt")

$proc.Id | Out-File -Encoding UTF8 $pidFile
Start-Sleep -Seconds 5

if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
    Write-Host ("Admin started, pid=" + $proc.Id) -ForegroundColor Green
    Write-Host "URL: http://127.0.0.1:8000/admin/dashboard/"
}
else {
    Write-Host "Admin process exited. See .report\admin_stderr.txt" -ForegroundColor Red
    Get-Content (Join-Path $reportDir "admin_stderr.txt") -Tail 30
}
