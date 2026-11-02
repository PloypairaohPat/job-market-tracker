#!/bin/sh
# Run the daily pipeline from cron (or the future Hetzner box).
# Same logic as scripts/windows/run_daily.ps1: repo root, the venv's python
# if present else `uv run python`, pass arguments through, and exit with
# the pipeline's exit code. Python does the logging (logs/daily-*.log).
#
# crontab example (07:15 server-local time; see docs/daily-operation.md):
#   15 7 * * *  /path/to/job-market-tracker/scripts/run_daily.sh
cd "$(dirname "$0")/.." || exit 1

# Start the database container first (same as run_daily.ps1). A failure is
# ignored: Docker may still be starting, and the runner waits for the
# database (--db-wait, default 300 s) before giving up with exit code 2.
# The server stack (deploy/) runs the pipeline from systemd, not this script.
if command -v docker >/dev/null 2>&1; then
    if docker compose up -d db; then
        echo "run_daily: ran 'docker compose up -d db'"
    else
        echo "run_daily: 'docker compose up -d db' failed; the runner will wait for the database"
    fi
else
    echo "run_daily: docker not found on PATH; not starting the database container"
fi

if [ -x .venv/bin/python ]; then
    exec .venv/bin/python -m src.pipeline.daily "$@"
fi
exec uv run python -m src.pipeline.daily "$@"
