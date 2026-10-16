# Register (or with -Uninstall remove) a Windows scheduled task that runs
# scripts\run_once.ps1 every POLL hours while you are logged on. Missed runs
# (PC asleep or off) start as soon as possible afterwards.
#   .\scripts\install_task.ps1               # every 12 h
#   .\scripts\install_task.ps1 -Hours 6
#   .\scripts\install_task.ps1 -Uninstall
param(
    [int]$Hours = 12,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$taskName = 'WeekendGetawayDeals'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    "Removed scheduled task $taskName."
    return
}

$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root '.env'))) {
    Write-Warning "No .env in ${root}: live runs need SERPAPI_API_KEY (see .env.example)."
}

$script = Join-Path $PSScriptRoot 'run_once.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Hours $Hours)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Search weekend hotel/terme deals and send alerts (python -m src.cli --once).' `
    -Force | Out-Null
"Registered ${taskName}: first run in 5 minutes, then every $Hours h. Log: data\logs\run.log"
