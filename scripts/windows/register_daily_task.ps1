# Registers (or removes) the Windows scheduled task that runs the daily
# pipeline. See docs/daily-operation.md.
#
#   .\scripts\windows\register_daily_task.ps1                    # 07:15, 13:15 and 19:15 local
#   .\scripts\windows\register_daily_task.ps1 -Time "06:45","12:45"
#   .\scripts\windows\register_daily_task.ps1 -Time "07:15"      # just one trigger
#   .\scripts\windows\register_daily_task.ps1 -Unregister
#
# One task, one daily trigger per time. run_daily.ps1 passes --once-per-day,
# so the first trigger that finds today's (UTC) ingestion missing does the
# work, and the later ones exit 0 at once: the extra triggers only matter on
# a day the earlier run was missed (laptop off, Docker down) or failed.
#
# The task runs as the current user, only when that user is logged on, so
# no password is stored. Settings (the same for every trigger):
#   -StartWhenAvailable        run as soon as possible after a missed start
#                              (laptop asleep at 07:15 -> runs on wake, once)
#   -RunOnlyIfNetworkAvailable
#   -MultipleInstances IgnoreNew
#   -ExecutionTimeLimit 1 hour
#
# Keep this file ASCII only: Windows PowerShell 5.1 misreads UTF-8 without a BOM.

param(
    [string[]]$Time = @("07:15", "13:15", "19:15"),
    [switch]$Unregister
)

$TaskName = "JobMarketTracker-Daily"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Unregistered scheduled task '$TaskName'."
    exit 0
}

# powershell.exe -File passes -Time "07:15","13:15" as ONE string, so split
# on commas as well as accepting a real array.
$times = @($Time | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($times.Count -eq 0) {
    Write-Error "Give at least one time, e.g. -Time `"07:15`""
    exit 1
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runScript = Join-Path $PSScriptRoot "run_daily.ps1"

$triggers = @()
foreach ($t in $times) {
    try {
        $at = [datetime]::ParseExact($t, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)
    } catch {
        Write-Error "Not a 24-hour HH:mm time: '$t' (e.g. 07:15)"
        exit 1
    }
    $triggers += New-ScheduledTaskTrigger -Daily -At $at
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`"" `
    -WorkingDirectory "$repoRoot"
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
    -Description "Job Market Tracker: daily ingestion, cleaning, skills, health (once per UTC day)" `
    -Action $action `
    -Trigger $triggers `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName':"
Write-Host "  runs   : powershell.exe -File `"$runScript`" (passes --once-per-day)"
Write-Host "  daily  : $($times -join ', ') local time (each catches up once on wake if missed)"
Write-Host "           the first run that finds today's UTC data missing does the work; the rest exit 0"
Write-Host "  as     : $env:USERDOMAIN\$env:USERNAME, only when logged on (no stored password)"
Write-Host ""
Write-Host "Check it:"
Write-Host "  Get-ScheduledTask -TaskName $TaskName | Select-Object -ExpandProperty Triggers"
Write-Host "  Get-ScheduledTaskInfo -TaskName $TaskName   # LastRunTime, LastTaskResult (0 = success), NextRunTime"
Write-Host "  Start-ScheduledTask -TaskName $TaskName     # run it now"
Write-Host "  Task Scheduler > Task Scheduler Library > $TaskName > History"
Write-Host "    (if History is empty: Actions pane > Enable All Tasks History)"
Write-Host "  logs\daily-YYYY-MM-DD.log under `"$repoRoot`""
Write-Host "  uv run python -m src.pipeline.health"
