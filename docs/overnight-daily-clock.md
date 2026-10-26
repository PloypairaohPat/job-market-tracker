# Overnight run: daily ingestion clock (Milestone A)

## Report

- **Branch:** `claude/daily-clock`, off `main` at `2c9170d` ("Merge pull request #1 from PloypairaohPat/claude/visa-sponsorship-layer"). This session's setup named a different working branch; per the brief, everything went to `claude/daily-clock`.
- **Commits on top of main `2c9170d`:** 9 commits plus this report (listed below). **Pushed:** yes, after every green commit. No force push, nothing to `main`, no PR.
- **STOP conditions:** none held.
  - `2c9170d` is in main's history.
  - `src/cleaning/data/skills.json` and `company_aliases.json` both exist.
  - The baseline was green.
  - `alembic heads` showed one head (`6f399ab4542e`).
  - main had no `src/pipeline/`, no `ingestion_runs` and no `.github/workflows/`.
- **Verification:** run on a clean local Postgres 16 `jobmarket_test` database (127.0.0.1), dropped and recreated before every commit. Versions: Python 3.13, SQLAlchemy 2.1.6, alembic 1.20.1, psycopg2-binary 2.9.13, pytest 9.1.1, ruff 0.17.2.

| Check | Baseline (clean main) | Final |
|---|---|---|
| `pytest` with `TEST_DATABASE_URL` | 310 passed, 0 failed, 0 skipped | **363 passed, 0 failed, 0 skipped** |
| `pytest` on Python 3.11.15 (via `uv python install 3.11`) | n/a | **362 passed** (before the stretch commit added 1 test) |
| `ruff check .` | clean | clean |
| `ruff format --check .` (whole repo) | 4 files would be reformatted | **clean**, 89 files |
| `alembic upgrade head && downgrade base && upgrade head` on a fresh database | clean | clean (new head `a02471448340`) |
| `make views` on a fresh alembic-built database, run twice | 6 views | **7 views** applied, twice |
| pwsh parse check of the two `.ps1` files | n/a | **not run**: one attempt, `apt-get install -y powershell` found no package. The scripts are ASCII-checked but were not executed or parse-checked |
| GitHub Actions CI on the branch | n/a | run #1 (workflow commit `b067f33`): **success** on 3.11 and 3.12, 362 passed with integration tests running. Run #2 (stretch `0c55460`): **success**. Run #3 (`7aaf24f`): **success**. This report's own run was pushed after writing, so it isn't recorded here |

- **Compare:** https://github.com/PloypairaohPat/job-market-tracker/compare/main...claude/daily-clock?expand=1
- **No live API call was made.**
  - No Adzuna or USAJobs credentials exist in this environment (no such variables are set).
  - Every test uses a fake HTTP session inside the real clients (`tests/pipeline_fakes.py`), the existing `FixtureBackedClient`s, or a client factory that refuses to build.
  - The only manual runs were `run_daily.sh --dry-run` with both sources skipped, and the health check. Neither builds a client.
  - I never ran `scripts/smoke_adzuna.py` or an ingest `main()` against a real API.

## What shipped

| # | Commit | What |
|---|---|---|
| 0 | `93acc1b` | `ruff format` (0.17.2) on the four unformatted files; `/logs/` in .gitignore |
| 1 | `ed7ba20` | `ingestion_runs` model and migration, `run_log.py`, secret redaction (filter, plus masking at source in both clients) |
| 2 | `4669929` | Monthly Adzuna budget guard; `ADZUNA_MONTHLY_RESERVE`; `ingest_adzuna.main` uses it |
| 3 | `9cdd7b1` | `python -m src.pipeline.daily` / `make daily`: advisory lock, dated log, per-source failure isolation |
| 4 | `449db2e` | `v_ingestion_daily` view, `python -m src.pipeline.health` / `make health`; the daily runner calls it last |
| 5 | `d13d12e` | `run_daily.ps1`, `register_daily_task.ps1`, `run_daily.sh`, `docs/daily-operation.md`, README and data dictionary |
| 6 | `b067f33` | `.github/workflows/ci.yml`, matrix 3.11 and 3.12. The push was accepted, so no `docs/ci-workflow.yml` fallback was needed |
| 7 | `0c55460` | Stretch: the sponsor-match finder still proposes longer variants when an exact key matches |
| 7b | `7aaf24f` | Docstring reword so acceptance #8's grep matches only fake test values |
| 8 | *(this commit)* | This report |

**0. Formatting baseline.** Formatting only, no logic, using ruff 0.17.2 (newer than the 0.16.10 in the brief's facts, but it flagged the same four files). CI pins `ruff==0.17.2`.

**1. Run log and redaction.**
- `ingestion_runs` has these columns: id, source, started_at, finished_at, status, calls_made, pages_fetched, jobs_processed, jobs_new, snapshot_date, params (JSONB, never credentials), and error (redacted, at most 2,000 characters). It is indexed on (source, started_at).
- `recorded_run()` commits a `running` row, then always closes it:
  - `ok`;
  - `partial`, when the per-run cap cut the run short;
  - `failed`, on any exception, after which it re-raises.
- `record_terminal_run()` writes `skipped_budget` runs and runs that failed before starting.
- `jobs_new` is the job count by source before and after the run. `calls_made` comes from the client, retries included.
- `run_ingestion` in both modules takes an optional `stats=`, so existing callers and tests are unchanged.
- Both ingest modules gained `build_client(settings, max_calls)` and `run_logged(...)`, and their `main()` uses them with the same CLI flags. Dry runs write no row.
- Redaction: `redact(text, secrets)` and `RedactingFilter` (in `src/utils/redaction.py`) mask the Settings credentials and any `app_id=` or `app_key=` value, including in tracebacks.
- I also mask the `requests` error text inside both clients **before** they log it or raise it (`raise ... from None`). That way the error a CLI prints to stderr carries no key either, which a logging filter alone can't guarantee.
- Tested with a fake `requests.ConnectionError` whose message contains `app_id=FAKEID&app_key=FAKEKEY`: neither the stored error nor the captured log output contains FAKEKEY or FAKEID.

**2. Budget guard.**
- `used = max(month's adzuna calls_made sum, month's adzuna raw_responses count)`.
- `cap = min(--max-calls, (budget − used − reserve) // days left incl. today)`.
- If the cap is ≤ 0, no client is built and a `skipped_budget` row and a warning are written, with exit 0.
- Each run logs "used N of BUDGET this month, cap for this run C".
- `ingest_adzuna.main` uses it, and `--dry-run` is capped too because it still makes real calls.
- Tests cover day 1 (cap 31), mid-month, the last day (75 → capped to 60, then 15), an exhausted month, raw-response history (and the larger of the two counts), month rollover, the client getting the cap, and `main()` skipping with an exhausted month.

**3. Daily runner.**
- Steps: adzuna → usajobs → cleaning (`run_steps(ALL_STEPS)`, factored out of `apply_cleaning.main` with the same computation) → skills → health. They are called in-process, with injectable client factories.
- A failing source is recorded and the run continues. Missing credentials give a `failed` row whose error is "Missing required environment variable(s): ADZUNA_APP_KEY", with no value.
- `pg_try_advisory_lock(0x4A4D5444)` is held on a dedicated AUTOCOMMIT connection.
- Logs go to stdout and `logs/daily-<UTC date>.log` (UTF-8, appended, redacted), and the run ends with a one-screen summary. The exit code is 1 if any step that ran failed.
- `--dry-run` is plan-only (see Q8).
- Tests: a full run; a second same-day run (no new snapshots, two run rows per source, the log appended); Adzuna failing while the rest runs (exit 1); missing credentials; the lock blocking a second runner whose lock is held from another connection; skip and dry-run; and a dry run with missing credentials writing nothing.

**4. Health.**
- `v_ingestion_daily` is built on `job_snapshots` joined to jobs, so pre-run-log days show up. Run columns are 0 or NULL before the run log existed.
- `health.py` implements H1–H6 and the INFO progress lines exactly as specified. It is read-only (it rolls back, and a test asserts nothing was written), supports `--json`, and exits 1 only on a FAIL.
- Tests use a fixed `now` and cover every PASS/WARN/FAIL edge (25 h / 26 h / 27 h; 849 / 850 / 999 / 1000 calls; a 40/50/60% drop), the streak across a one-day gap, history with no run rows, and the view's per-source split.

**5. Scheduling and docs.**
- `run_daily.ps1` sets the repo root from `$PSScriptRoot` and uses `.venv\Scripts\python.exe`, else `uv run python`, then exits with `$LASTEXITCODE`. It also sets `PYTHONUTF8=1` so a console-less run can't fail encoding a job title. It writes no files.
- `register_daily_task.ps1` takes `-Time` (default 07:15) and `-Unregister`. It registers the task as the current user, Interactive logon only (no stored password), with StartWhenAvailable, RunOnlyIfNetworkAvailable, IgnoreNew and a 1-hour limit, then prints how to check it.
- Both `.ps1` files are ASCII only (checked).
- `run_daily.sh` is POSIX sh (`sh -n` clean). I ran it from another directory.
- `docs/daily-operation.md` covers everything the brief lists.
- The README's old cron line is replaced by a "Daily operation" section. The Makefile has `daily` and `health` targets with help comments, and the data dictionary has a "Daily clock" section.

**6. CI.**
- On push and pull_request, with `contents: read` and no secrets.
- A `postgres:16` service with a `pg_isready` health check.
- Steps: `pip install -e ".[dev]"`, then `ruff==0.17.2`, `ruff check`, `ruff format --check`, the alembic round trip, and `pytest` against 127.0.0.1.
- I installed Python 3.11.15 locally and ran the full suite once: 362 passed. The matrix is therefore ["3.11", "3.12"].

**7. Stretch.** `find_sponsor_match_candidates` now skips only the exact pair, so "fakeco holdings" is proposed for company "fakeco" even when an LCA employer "fakeco" exists. Tests use FAKE names. The one data-dictionary sentence describing the old behaviour was updated. Nothing else in the visa layer changed.

## Parked questions

| Q | Question | Recommendation (built) |
|---|---|---|
| 1 | Prefect vs the plain scheduled-task runner | (a) plain runner now; Prefect in Phase 6 |
| 2 | Adzuna billing month and reserve size | (a) UTC calendar month, reserve 25 |
| 3 | Health thresholds (26 h, 50% drop, 85% budget) | (a) keep until a month of real data |
| 4 | `removed_at` lifecycle | (a) leave unset; derive presence from job_snapshots in a view |
| 5 | Task Scheduler: logged-on only vs always; WakeToRun | (a) logged-on only, no WakeToRun |
| 6 | Where to pin ruff | (a) CI only |
| 7 | Log retention | (a) keep everything |
| 8 | Meaning of `daily --dry-run` | (a) plan only: no calls, no writes |
| 9 | Do `partial` and `skipped_budget` Adzuna runs count as success? | (a) yes, exit 0 |
| 10 | H1 FAILs on a month of only `skipped_budget` runs | (a) keep: no Adzuna data is arriving |

### Q1. Prefect vs the plain scheduled-task runner
- **What I found:** the guide plans Prefect for Phase 6. Prefect isn't a dependency, and the brief allows no new runtime dependencies. One daily job, with a run log, a health check and an advisory lock, covers what Prefect would add for a single flow (retries are already in the clients).
- **Options:**
  - (a) Plain `python -m src.pipeline.daily` run by Task Scheduler or cron.
  - (b) Wrap the same step functions in a Prefect flow later. The steps are in-process functions, so this is a thin layer.
  - (c) Adopt Prefect now.
- **Recommendation:** (a), built. Do (b) in Phase 6 if you want the Prefect UI on the portfolio; the runner's `STEP_FUNCS` map directly onto tasks.

### Q2. Adzuna billing month and reserve
- **What I found:** the free tier is "1,000 calls a month", but I couldn't check (and didn't try to check) whether Adzuna counts by calendar month, from the signup date, or over a rolling 30 days.
- **Options:**
  - (a) UTC calendar month (`month_bounds()`).
  - (b) A month anchored on a configurable signup day (`ADZUNA_BILLING_DAY`).
  - (c) A rolling 30 days.
- **Recommendation:** (a), built, with a reserve of 25. If Adzuna's dashboard shows a different reset day, (b) is a small change confined to `month_bounds()` and `days_left_in_month()`. A reserve of 25 covers one smoke test (1 call) and one manual 18–24-call run.

### Q3. Health thresholds
- **What I found:** the defaults are 26 hours (a daily run plus slack for a late wake), more than a 50% drop, and 85% of the budget. They are all constants at the top of `src/pipeline/health.py`.
- **Options:**
  - (a) Keep them.
  - (b) Tighten H1 to 25 hours, or loosen it to 30 hours if the laptop often wakes late.
  - (c) Make them Settings variables.
- **Recommendation:** (a), built. Revisit after a month of real `v_ingestion_daily` rows. H3 especially should be tuned on real day-to-day variance.

### Q4. `removed_at` lifecycle
- **What I found:** not seeing a job isn't the same as the job closing. Adzuna returns at most 250 results per query (5 pages × 50), so live postings drop out of view, and a skipped or failed day hides everything.
- **Options:**
  - (a) Leave `removed_at` unset, and derive presence from `job_snapshots` in a view (e.g. last snapshot date per job, with a gap length).
  - (b) Mark a job removed after N consecutive ok runs without it, for USAJobs only, since its result sets are small enough to be complete.
  - (c) Mark it removed after N days, for both sources.
- **Recommendation:** (a). It is recomputable and never wrong about "closed". Nothing was built for this, since it's out of scope.

### Q5. Task Scheduler options
- **What I found:** "Run whether user is logged on or not" needs a stored password (or S4U, which loses network credentials). WakeToRun would wake the laptop at 07:15, which matters only if it sleeps through the morning.
- **Options:**
  - (a) Only when logged on, no WakeToRun.
  - (b) Add `-WakeToRun` to `New-ScheduledTaskSettingsSet`.
  - (c) Run whether logged on or not, with a stored password.
- **Recommendation:** (a), built. Try (b) if the health check shows a pattern of missed mornings.

### Q6. Where to pin ruff
- **What I found:** the formatter's output differs between ruff versions. `pyproject.toml` says `ruff>=0.4`.
- **Options:**
  - (a) Pin `ruff==0.17.2` in CI only.
  - (b) Also pin it in the `[dev]` extras.
  - (c) No pin.
- **Recommendation:** (a), built. (b) would make local and CI identical; it's worth doing if you ever see "passes locally, fails in CI" on formatting.

### Q7. Log retention
- **What I found:** one small file per UTC day, at most a few hundred KB, and nothing deletes them.
- **Options:**
  - (a) Keep everything.
  - (b) A `--prune-logs DAYS` flag.
  - (c) Rotate by size.
- **Recommendation:** (a), built. Deleting files on your machine is out of scope.

### Q8. What `daily --dry-run` means
- **What I found:** the ingest CLIs' `--dry-run` fetches without writing. That still spends real Adzuna calls, and the guard can't see them because no run row is written.
- **Options:**
  - (a) A plan only: log the budget decision and the steps, with no calls and no writes.
  - (b) Fetch without writing, like the ingest CLIs.
- **Recommendation:** (a), built. `ingest_adzuna --dry-run` keeps its old behaviour but is now capped by the monthly guard too.

### Q9. `partial` and `skipped_budget` count as success
- **What I found:** both mean the budget guard did its job.
- **Options:**
  - (a) Exit 0.
  - (b) Exit 1 on `partial` so Task Scheduler shows it.
- **Recommendation:** (a), built. H3, H4 and the run log make a partial day visible anyway.

### Q10. H1 with only `skipped_budget` runs
- **What I found:** per the brief, H1 needs an ok or partial run within 26 hours. After an exhausted month, Adzuna FAILs H1 daily until the 1st.
- **Options:**
  - (a) Keep it, since it is true that no Adzuna data is arriving, and H4 says why.
  - (b) Downgrade H1 to WARN when the latest run is `skipped_budget`.
- **Recommendation:** (a), built. With the per-day spreading, an exhausted month needs manual runs well beyond the reserve.

## What the owner must do locally

Nothing here can touch your laptop. In **Windows PowerShell**, from the repo root, after merging the PR:

```powershell
# 1. pull main
git checkout main
git pull
uv sync                                   # or: uv pip install -e ".[dev]"; creates/updates .venv

# 2. .env -- edit with Notepad or VS Code, NEVER with echo / >> (UTF-16 NUL bytes).
#    DATABASE_URL must name the driver:
#      DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/jobmarket
#    Optional new setting: ADZUNA_MONTHLY_RESERVE=25
notepad .env

# 3. schema + views (Postgres must be up: docker compose up -d)
uv run alembic upgrade head               # adds ingestion_runs
make views                                # if make isn't installed:
uv run python scripts/apply_views.py      # -> "7 views applied"

# 4. health BEFORE scheduling anything: job_snapshots history already
#    answers "has ingestion been running?" (H1 will WARN "no run log yet")
uv run python -m src.pipeline.health

# 5. one supervised run (plan first: no calls, no writes)
uv run python -m src.pipeline.daily --dry-run
uv run python -m src.pipeline.daily
Get-Content (Get-ChildItem logs\daily-*.log | Sort-Object Name | Select-Object -Last 1).FullName -Tail 15

# 6. register the scheduled task (daily 07:15 local)
.\scripts\windows\register_daily_task.ps1
#    if scripts are blocked:
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\register_daily_task.ps1
Get-ScheduledTaskInfo -TaskName JobMarketTracker-Daily

# 7. the next day
Get-ScheduledTaskInfo -TaskName JobMarketTracker-Daily    # LastTaskResult 0 = success
uv run python -m src.pipeline.health                      # expect every check PASS
```

CI is already in `.github/workflows/ci.yml`; nothing needs moving.

**Numbers to sanity-check:**

- **Calls used this month** (health H4 / the "used N of 1000" log line). Compare it with Adzuna's own dashboard. If Adzuna shows more, its month or counting differs (Q2). After one daily run, expect at most 30 (6 queries × up to 5 pages).
- **Snapshot rows per day per source:**
  ```powershell
  docker compose exec db psql -U postgres -d jobmarket -c "select * from v_ingestion_daily order by snapshot_date desc, source limit 14;"
  ```
  - Adzuna should be stable day to day, at most 6 queries × 250 results, deduped.
  - USAJobs should be a few hundred at most.
  - `n_runs` 1 and `n_ok_runs` 1 per day once the task is running. Days before today show `n_runs` 0 and NULL calls (pre-run-log history).
- **Streak and progress** (health P1–P4):
  - "first snapshot" should match when you started ingesting.
  - "snapshot days" counts every day you ran.
  - "current streak" counts consecutive days ending today or yesterday. It resets after any missed day, which is expected if earlier ingestion was manual.

## Surprises

- **The secret leak went beyond logs.** The `AdzunaError` raised after a network failure embedded the same URL. A CLI crash printed it to stderr, and the old README cron line sent stderr to the log file. A logging filter can't catch that, so both clients now mask the text at the source and drop the exception chain (`from None`). The filter remains as the second layer.
- **ruff version.** The VM had ruff 0.17.2, not the 0.16.10 in the brief's facts. It flagged exactly the same four files, and CI pins 0.17.2.
- **`ingest_adzuna --dry-run` spends real calls.** It fetches and only skips the writes, so its calls never reach `ingestion_runs`. It is now capped by the guard. The daily runner's `--dry-run` is plan-only instead (Q8).
- **H1 FAILs during an exhausted month.** That follows from the brief's definition (only ok or partial runs count). See Q10.
- **CI on Node 20.** GitHub warns that `actions/checkout@v4` and `actions/setup-python@v5` target Node 20 and are being forced onto Node 24. CI still passes; bump to newer majors when they're out.
- **No pwsh.** `apt-get install -y powershell` found no package, which used up the one allowed attempt. The `.ps1` files are ASCII-checked but not parse-checked. The first `register_daily_task.ps1` run on your laptop is their first real execution, so read its printed summary.
- **The full suite takes ~90 s locally** (it was ~30 s). The daily-runner tests run the whole pipeline over the fixtures, about 600 upserts per run, several times. CI takes ~45 s.

## Suggested PR title

**Daily ingestion clock: run log, Adzuna budget guard, daily runner, health check, Windows task and CI**

<details>
<summary>PR description (ready to paste)</summary>

## Summary

Makes the daily ingestion clock real, safe and observable (Milestone A). The portfolio targets (90+ days of snapshots, 60+ days of daily ingestion, 10,000+ jobs) only accumulate if ingestion fires every day, and a missed day can't be backfilled.

- **Run log.** `ingestion_runs` holds one row per run per source: `running`, then `ok`, `partial`, `failed` or `skipped_budget`. It records calls made (retries included), pages, jobs processed and new, params (never credentials), and a redacted error.
- **Secret redaction.** A `requests` network error embeds the full URL, Adzuna's `app_id` and `app_key` included. Both clients now mask it at the source, and a `RedactingFilter` on the CLI and runner log handlers is a second layer. Tested with FAKEKEY.
- **Monthly Adzuna budget guard.** `cap = min(--max-calls, (1000 − used − reserve) // days left)`, where `used` is the larger of this month's logged calls and its raw-response count. If the cap is ≤ 0, no call is made and the run is `skipped_budget`.
- **Daily runner.** `python -m src.pipeline.daily` (`make daily`) runs adzuna → usajobs → cleaning → skills → health. A failing source doesn't stop the rest. A Postgres advisory lock allows one instance. It writes `logs/daily-YYYY-MM-DD.log` and exits 1 if any step fails.
- **Health check.** `python -m src.pipeline.health` (`make health`) is read-only and has six checks (run freshness, snapshot freshness, volume drop, budget, cleaning freshness, failed runs) plus progress against the targets. It exits 1 on any FAIL. The new `v_ingestion_daily` view gives one row per UTC day per source.
- **Scheduling.** `scripts/windows/register_daily_task.ps1` registers a daily 07:15 task (logged-on only, no stored password; catches up after sleep), and `scripts/run_daily.sh` is the cron entry point. The operating guide is `docs/daily-operation.md`.
- **CI.** `.github/workflows/ci.yml` runs ruff check and format, the alembic round trip and the full suite against a Postgres 16 service, on 3.11 and 3.12, with no secrets.
- **Also:**
  - The repo-wide `ruff format` baseline is clean.
  - `/logs/` is ignored.
  - The sponsor-match finder now proposes longer variants of an exactly matched employer.

## Testing

- `pytest` with `TEST_DATABASE_URL`: 310 → **363 passed**, 0 failed, 0 skipped. 3.11.15 was verified locally (362 before the stretch test).
- `ruff check .` and `ruff format --check .` are clean on the whole repo (ruff 0.17.2).
- The alembic round trip is clean on a fresh database, and `make views` applies 7 views, twice.
- GitHub Actions CI is green on 3.11 and 3.12.
- No live API call was made: every test uses fake HTTP sessions inside the real clients, or fixture-backed clients.

## Open questions

10 parked decisions are in `docs/overnight-daily-clock.md`, each with the default that was built: Prefect, the billing month and reserve, health thresholds, the `removed_at` lifecycle, Task Scheduler options, ruff pinning, log retention, the meaning of dry-run, and two exit-code semantics.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01ATh4ABgiML8G58MzgJ36ZP

</details>
