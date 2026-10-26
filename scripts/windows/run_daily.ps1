# Runs the Job Market Tracker daily pipeline (python -m src.pipeline.daily).
# This is what the "JobMarketTracker-Daily" scheduled task runs; see
# docs/daily-operation.md and scripts/windows/register_daily_task.ps1.
#
# It writes no files itself: Python logs to stdout and to
# logs\daily-YYYY-MM-DD.log (UTC date, UTF-8). Extra arguments are passed
# through, e.g.:  .\scripts\windows\run_daily.ps1 --skip adzuna
#
# Keep this file ASCII only: Windows PowerShell 5.1 misreads UTF-8 without a BOM.

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -Path $repoRoot

# Job titles can contain non-ASCII text; make Python's stdout UTF-8 so a
# console-less scheduled run never fails on encoding.
$env:PYTHONUTF8 = "1"

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython -m src.pipeline.daily @args
} else {
    & uv run python -m src.pipeline.daily @args
}
exit $LASTEXITCODE
