#!/bin/sh
# Run the daily pipeline from cron (or the future Hetzner box).
# Same logic as scripts/windows/run_daily.ps1: repo root, the venv's python
# if present else `uv run python`, pass arguments through, and exit with
# the pipeline's exit code. Python does the logging (logs/daily-*.log).
#
# crontab example (07:15 server-local time; see docs/daily-operation.md):
#   15 7 * * *  /path/to/job-market-tracker/scripts/run_daily.sh
cd "$(dirname "$0")/.." || exit 1
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python -m src.pipeline.daily "$@"
fi
exec uv run python -m src.pipeline.daily "$@"
