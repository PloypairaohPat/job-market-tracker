# Daily operation

The project's targets are **90+ days of daily snapshots, 60+ days of daily ingestion and 10,000+ unique jobs**. They only accumulate if ingestion really runs every day, and **a missed day can never be backfilled**, because a snapshot records what the APIs showed that day. This page covers running the clock on the Windows laptop, checking it, and reading the health check.

Commands below are for Windows PowerShell with `uv`, run from the repo root.

> **Never create or edit `.env` with PowerShell `echo` or `>>`.** Windows PowerShell 5.1 writes UTF-16, which puts NUL bytes in the file (that's how README.md got corrupted once). Python's dotenv then can't read it. Use Notepad or VS Code, or `Copy-Item .env.example .env` and then edit it.

## What runs

`uv run python -m src.pipeline.daily` (or `make daily`) runs these steps in order:

1. **adzuna**: the six target queries, up to 5 pages each (at most 30 calls). The monthly budget guard caps the run (see below).
2. **usajobs**: the keyword queries plus the three occupational series (1560, 1515, 1530).
3. **cleaning**: every `apply_cleaning` step (seniority, salary, remote, metro, companies, scope, visa).
4. **skills**: taxonomy sync and skill extraction.
5. **health**: the read-only check below.

Each source writes one row to `ingestion_runs` (see `docs/data_dictionary.md`).

If one source fails (an API error or missing credentials), it is recorded as a `failed` run and the rest still runs. Cleaning and skills only read the database and are idempotent, so they're always safe to run.

Only one run can be active at a time, enforced with a Postgres advisory lock. A second run that starts while one is active logs that and exits 0.

Exit code 0 means every step that ran succeeded. A `skipped_budget` or `partial` Adzuna run counts as success, because that is the guard working.

The log goes to the console and to `logs\daily-YYYY-MM-DD.log`. The date in the file name is the UTC date. The file is UTF-8 and is appended to on each run. Credentials are masked as `***` in the log. Nothing is ever rotated or deleted.

Useful flags:

```powershell
uv run python -m src.pipeline.daily --dry-run                 # plan only: budget decision + steps; no API calls, no writes
uv run python -m src.pipeline.daily --skip adzuna             # e.g. save Adzuna calls on a re-run
uv run python -m src.pipeline.daily --skip adzuna usajobs     # just cleaning + skills + health
```

## Registering the scheduled task (Windows)

```powershell
.\scripts\windows\register_daily_task.ps1                # daily at 07:15 local time
.\scripts\windows\register_daily_task.ps1 -Time "06:45"  # another time
.\scripts\windows\register_daily_task.ps1 -Unregister
```

This creates a task named **JobMarketTracker-Daily**. It runs `scripts\windows\run_daily.ps1` as you, only while you're logged on, so no password is stored. The task settings are:

- start as soon as possible after a missed start
- only run if the network is available
- ignore a new instance if one is still running
- stop after 1 hour

`run_daily.ps1` uses `.venv\Scripts\python.exe` if it exists, otherwise `uv run python`.

If PowerShell refuses to run the script ("running scripts is disabled"), run this once:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\register_daily_task.ps1
```

The task itself always runs with `-ExecutionPolicy Bypass`.

### Checking that it ran

```powershell
Get-ScheduledTaskInfo -TaskName JobMarketTracker-Daily   # LastRunTime, LastTaskResult (0 = success, 1 = a step failed)
Start-ScheduledTask   -TaskName JobMarketTracker-Daily   # run it now
Get-ChildItem logs                                       # one daily-YYYY-MM-DD.log per UTC day
Get-Content logs\daily-2026-10-27.log -Tail 20           # the summary is at the end
uv run python -m src.pipeline.health                     # or: make health
```

For the task's own history, open **Task Scheduler → Task Scheduler Library → JobMarketTracker-Daily → History**. If the tab is empty, click *Enable All Tasks History* in the Actions pane.

### Why 07:15 local

Snapshot dates are **UTC** dates. If a run lands near UTC midnight (about 7–9 pm US Eastern), one evening's run can fall on one UTC date and the next evening's slightly earlier run on the same date again. That gives two runs on one UTC date and none on the next: a lost day, and a broken streak.

07:15 anywhere in the continental US is 11:15–15:15 UTC (EDT through PST), well away from midnight on either side, even with the catch-up delay after waking the laptop.

### The laptop caveat

- **Asleep** at 07:15: the task runs once when the laptop wakes ("start when available"). That's fine.
- **Off or away** all day: that day is lost for good. The health check will show it (H2 WARN/FAIL and a reset streak), but nothing can recover it.

The durable fix is running the same pipeline on an always-on server: **Milestone D**. [docs/deploy.md](deploy.md) sets it up with a systemd timer at 11:15 UTC, and its cut-over makes sure the laptop and the server never both ingest on the same UTC day. Don't add a cron job as well.

## The Adzuna budget

Adzuna's free tier is **1,000 calls a month**. A normal daily run is at most 6 queries × 5 pages = **30 calls**, and 30 × 31 = 930, which fits only if nothing else spends calls. So every Adzuna run, from the daily runner or `python -m src.ingestion.ingest_adzuna`, is capped:

```
used = max( sum of ingestion_runs.calls_made for adzuna this UTC month,
            count of adzuna raw_responses fetched this UTC month )
cap  = min( --max-calls, (1000 - used - reserve) // days left in the month, today included )
```

- **calls_made** counts every HTTP attempt, retries and failures included. raw_responses only holds successful pages, but it is the only record from before the run log existed, so the larger of the two is used.
- **reserve** (`ADZUNA_MONTHLY_RESERVE`, default 25) is held back for manual runs and `scripts/smoke_adzuna.py`.
- **Spreading the remainder over the days left** guarantees later days in the month still get calls. On day 1 with nothing used, the cap is (1000 − 0 − 25) // 31 = 31, which is at least 30, so a normal run is never throttled. If manual runs eat into the month, later daily runs get smaller caps instead of the month running dry on the 28th.
- If the cap is **≤ 0**, no request is made. The run is recorded as `skipped_budget` with a warning, and that is not an error (exit 0).

Each run logs a line like `used 420 of 1000 this month, cap for this run 30`. Health check H4 warns at 85% used and fails at 100%.

## The health check

```powershell
uv run python -m src.pipeline.health           # human-readable
uv run python -m src.pipeline.health --json    # machine-readable
```

The check is read-only and writes nothing. It exits **1 if any check FAILs**, otherwise 0 (WARNs don't fail it). The daily runner runs it last and includes the result in its summary.

| Check | PASS | WARN | FAIL | What to do |
|---|---|---|---|---|
| **H1** run freshness (per source) | latest `ok`/`partial` run finished ≤ 26 h ago | no run rows at all for the source yet (shows its latest `jobs.last_seen_at`) | older than 26 h, or no run ever ended ok/partial | Check `Get-ScheduledTaskInfo` and the latest log. A FAIL after a failed run means the API errored or credentials are missing; the error is in `ingestion_runs.error`. A month of only `skipped_budget` runs also shows here (see H4). |
| **H2** snapshot freshness | latest snapshot_date is today (UTC) | yesterday | older, or no snapshots | WARN early in the day is normal before the task has run. FAIL means at least one whole day was missed. Run `daily` now to save today, since past days are gone. |
| **H3** snapshot volume (per source) | latest day's distinct jobs within 50% of the previous snapshot day | dropped more than 50% | — | Usually a partial run (budget cut, or an API error mid-run) or an API-side change. Look at that day's runs and the log. |
| **H4** Adzuna budget | < 85% of the month used | ≥ 85% | ≥ 100% | Stop manual Adzuna runs for the month. The guard already protects the remaining days. |
| **H5** cleaning freshness | every job has a `job_visa_signals` row | some don't | — | Cleaning didn't run after the last ingestion: `uv run python -m src.pipeline.daily --skip adzuna usajobs`. |
| **H6** failed runs | none in the last 7 days | any | — | Read `ingestion_runs.error` for those runs (redacted, so no keys), and the matching day's log. |

The progress lines are INFO only and never fail:

- unique jobs against 10,000
- distinct snapshot days against 90
- the current streak of consecutive snapshot days ending today or yesterday, against 60
- the first snapshot date

Before scheduling anything, run the health check once. `job_snapshots` history already answers "has ingestion been running?", even from before the run log existed: H1 will WARN "no run log yet", and the progress lines show the real history.
