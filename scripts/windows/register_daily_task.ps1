# Registers (or removes) the Windows scheduled task that runs the daily
# pipeline once a day. See docs/daily-operation.md.
#
#   .\scripts\windows\register_daily_task.ps1                 # daily at 07:15 local time
#   .\scripts\windows\register_daily_task.ps1 -Time "06:45"
#   .\scripts\windows\register_daily_task.ps1 -Unregister
#
# The task runs as the current user, only when that user is logged on, so
# no password is stored. Settings:
#   -StartWhenAvailable        run as soon as possible after a missed start
#                              (laptop asleep at 07:15 -> runs on wake, once)
#   -RunOnlyIfNetworkAvailable
#   -MultipleInstances IgnoreNew
#   -ExecutionTimeLimit 1 hour
#
# Keep this file ASCII only: Windows PowerShell 5.1 misreads UTF-8 without a BOM.

param(
    [string]$Time = "07:15",
    [switch]$Unregister
)

$TaskName = "JobMarketTracker-Daily"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Unregistered scheduled task '$TaskName'."
    exit 0
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runScript = Join-Path $PSScriptRoot "run_daily.ps1"
$at = [datetime]::ParseExact($Time, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`"" `
    -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $at
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Job Market Tracker: daily ingestion, cleaning, skills, health" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName':"
Write-Host "  runs   : powershell.exe -File $runScript"
Write-Host "  daily  : $Time local time (catches up once on wake if the start was missed)"
Write-Host "  as     : $env:USERDOMAIN\$env:USERNAME, only when logged on (no stored password)"
Write-Host ""
Write-Host "Check it:"
Write-Host "  Get-ScheduledTaskInfo -TaskName $TaskName   # LastRunTime, LastTaskResult (0 = success)"
Write-Host "  Start-ScheduledTask -TaskName $TaskName     # run it now"
Write-Host "  Task Scheduler > Task Scheduler Library > $TaskName > History"
Write-Host "    (if History is empty: Actions pane > Enable All Tasks History)"
Write-Host "  logs\daily-YYYY-MM-DD.log under $repoRoot"
Write-Host "  uv run python -m src.pipeline.health"
