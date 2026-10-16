# One search -> store -> alert cycle, output appended to data\logs\run.log.
# Run by the scheduled task from install_task.ps1; extra arguments go to the CLI,
# e.g.  .\scripts\run_once.ps1 --demo --dry-run
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root 'data\logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir 'run.log'
# Keep one previous log once it passes 1 MB.
if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) {
    Move-Item -Force $log (Join-Path $logDir 'run.previous.log')
}

$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$python = if (Test-Path $venvPython) { $venvPython } else { 'python' }

$env:PYTHONIOENCODING = 'utf-8'
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm') ===" | Out-File -Append -Encoding utf8 $log
# Windows PowerShell 5.1 turns native stderr lines into errors; the CLI's progress goes there.
$ErrorActionPreference = 'Continue'
& $python -m src.cli --once @args *>&1 | ForEach-Object { "$_" } | Out-File -Append -Encoding utf8 $log
$code = $LASTEXITCODE
"exit $code" | Out-File -Append -Encoding utf8 $log
exit $code
