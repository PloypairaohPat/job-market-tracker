# Job Market Tracker

A self-hosted analytics platform that ingests live job posting data, extracts skill and salary intelligence, and surfaces trends in the data analytics labor market through dashboards and written analytical reports.

**Why it exists**: job seekers in analytics face information asymmetry — hidden salary bands, inconsistent skill descriptions, no visibility into market shape. This project builds a transparent, queryable view of that market, and in doing so demonstrates the full analyst workflow: **ingestion → cleaning → modeling → analysis → visualization → storytelling**.

> **Status:** two sources (Adzuna and USAJobs) ingested by a daily runner with a budget guard and a health check; a cleaning layer, skill tagging and a visa-sponsorship layer; sixteen SQL views with three investigations written up; six Metabase dashboards defined as code. A deploy kit for an always-on server is ready but not yet used. A report kit renders the first three written reports' tables, charts and methods from the views; their narrative comes next. See the [roadmap](#roadmap).

## In three minutes

I built a job-market analytics platform for data-analyst roles. Every day it pulls postings from two public APIs: Adzuna for commercial jobs and USAJobs for federal ones. It stores every raw response in Postgres, so history can be replayed. Then it cleans the messy parts: company names, salary formats, locations, seniority, remote status and skill mentions.

SQL views are the single source of truth for every metric. Metabase dashboards built on them show:

- the market's shape
- employer-disclosed salaries (never blended with Adzuna's predictions)
- skill demand in commercial vs federal postings
- how much employers actually disclose

Grouped numbers sit next to their n, with their caveats.

A snapshot records what the APIs showed that day, so a missed day can never be backfilled: the daily clock, its health check and its API budget matter as much as the analysis. Written reports answering specific market questions come next.

I built it to understand the market I'm entering, and to show the whole analyst workflow end to end: **ingestion → cleaning → modeling → analysis → visualization → storytelling**.

## How it works

```mermaid
flowchart TD
    subgraph clock["Daily clock: Task Scheduler on the laptop today, a systemd timer on the server"]
        direction LR
        runner{{"Daily runner<br/>src.pipeline.daily"}}
        budget{"Adzuna budget guard<br/>monthly call budget"}
        runlog[("ingestion_runs<br/>run log")]
        health["Health check<br/>src.pipeline.health"]
        runner -->|"before ingesting"| budget
        runner -->|"one row per source"| runlog
        runner -->|"last step"| health
        runlog -.->|"calls used this month"| budget
    end

    subgraph sources["Sources"]
        direction LR
        adzuna["Adzuna API<br/>commercial postings"]
        usajobs["USAJobs API<br/>federal postings"]
        lca["DOL LCA disclosure files<br/>loaded by hand"]
    end

    raw[("raw_responses<br/>every response, verbatim")]
    core[("jobs · companies · locations<br/>job_snapshots, one per job per UTC day")]

    subgraph enrich["Cleaning, skills and visa: the runner's next steps"]
        direction LR
        clean["Cleaning<br/>seniority · salary · remote · metro · companies"]
        skills["Skills<br/>taxonomy extractor"]
        visa["Visa layer<br/>posting signals · LCA sponsor match"]
    end

    views[["SQL views<br/>sql/views/v_*"]]
    dash["Metabase dashboards<br/>read-only role"]
    reports["Findings and reports<br/>docs/"]

    budget -.-> adzuna
    runner -.-> usajobs
    adzuna --> raw
    usajobs --> raw
    raw -->|"parse"| core
    core --> enrich
    lca --> visa
    enrich --> views
    runlog --> views
    views --> dash
    views --> reports
```

Three architectural decisions carry the design:

1. **Raw-then-normalized** — every API response is stored verbatim as JSONB *before* parsing. Parsing bugs and schema changes are fixed by replaying history, never by re-fetching.
2. **Idempotent ingestion** — jobs are keyed by `(source, external_id)`; re-running a sync never duplicates data and always converges on the latest observed state. Verified by integration tests against real Postgres.
3. **Daily snapshots from day one** — `job_snapshots` records each job's observed state per day, so time-series analysis (posting lifetimes, salary changes, demand shifts) becomes possible the moment enough days accumulate.

## Tech stack

Python 3.11+ · PostgreSQL 16 · SQLAlchemy 2 · Alembic · pandas · Plotly · Jupyter · Metabase · Docker Compose · Caddy · systemd · pytest · ruff · GitHub Actions. Rationale for the original choices is in [`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md).

## Quick start

**Prerequisites**: Docker, Python 3.11+, and [`uv`](https://docs.astral.sh/uv/) (or plain `pip`).

```bash
git clone https://github.com/YOUR_USERNAME/job-market-tracker.git
cd job-market-tracker

# 1. Environment
cp .env.example .env               # then fill in Adzuna credentials (see below)

# 2. Database
docker compose up -d               # Postgres 16 on localhost:5432
uv sync                            # or: pip install -e ".[dev]"
uv run alembic upgrade head        # apply schema

# 3a. Try it WITHOUT an API key (synthetic demo data)
uv run python scripts/seed_demo_data.py

# 3b. Or ingest real data (requires free Adzuna credentials)
uv run python scripts/smoke_adzuna.py                 # 1 API call — sanity check
uv run python -m src.ingestion.ingest_adzuna          # full ingestion

# 4. Explore
uv run jupyter lab notebooks/01_initial_exploration.ipynb
```

**Adzuna credentials**: register free at [developer.adzuna.com](https://developer.adzuna.com/), create an app, and put `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` in `.env`. Free tier is 1,000 calls/month; the ingestion CLI enforces a per-run budget (`--max-calls`, default 60) so development iteration can't burn the month.

### Ingestion CLI

```bash
python -m src.ingestion.ingest_adzuna --help
  --queries [Q ...]   override the default six analyst-role queries
  --max-pages N       pages per query (default 5 → ≤250 jobs/query)
  --max-calls N       hard API budget for this run (default 60)
  --dry-run           fetch and count, write nothing
```

## How it runs

| | Laptop (today) | Server (after the cut-over) |
|---|---|---|
| Postgres | Docker (`docker-compose.yml`), port 5432 on the laptop | Docker (`deploy/docker-compose.prod.yml`), no published port |
| Daily run | Task Scheduler, 07:15 local time | systemd timer, 11:15 UTC |
| Dashboards | Metabase on http://localhost:3000 | Metabase behind Caddy (HTTPS); only public-dashboard links are reachable, and admin goes through an SSH tunnel |
| Backups | not automated | nightly `pg_dump`, newest 14 kept |
| Guide | [`docs/daily-operation.md`](docs/daily-operation.md), [`docs/dashboard.md`](docs/dashboard.md) | [`docs/deploy.md`](docs/deploy.md) |

Exactly one machine ingests on any UTC day. The cut-over in [`docs/deploy.md`](docs/deploy.md) moves the clock to the server without losing a day or spending Adzuna calls twice, and only then turns on public dashboard links.

### Daily operation

The portfolio targets (90+ days of snapshots, 60+ days of daily ingestion, 10,000+ jobs) only accumulate if ingestion fires every day, and a missed day can never be backfilled. One command runs the whole day, both sources, then cleaning, skills and a health check, with a dated log and the monthly Adzuna budget enforced:

```bash
uv run python -m src.pipeline.daily      # or: make daily
uv run python -m src.pipeline.health     # is the clock running? exit 1 on any FAIL (make health)
```

On Windows, `scripts/windows/register_daily_task.ps1` registers it as a daily scheduled task; on the server, a systemd timer runs it in the pipeline container ([`docs/deploy.md`](docs/deploy.md)). Setup, what each health check means, and the budget arithmetic: [`docs/daily-operation.md`](docs/daily-operation.md). On the laptop, `uv run python -m src.doctor` (or `make doctor`) checks the whole setup read-only and prints the command that fixes each problem; the routine after every `git pull` and a troubleshooting table are in [`docs/laptop-runbook.md`](docs/laptop-runbook.md).

### Dashboards

Six Metabase dashboards (ingestion health, market overview, salary, skills, transparency, and a private visa outlook) are defined as files in `dashboards/`. They read only the `v_*` SQL views, through a read-only database role. Metabase runs in an opt-in compose profile:

```bash
uv run python -m src.dashboard.reader_role   # read-only role (make bi-grant)
docker compose --profile bi up -d            # Metabase on http://localhost:3000 (make bi-up)
uv run python -m src.dashboard.provision     # build/refresh every dashboard (make bi-provision)
```

Setup, what each dashboard shows and its caveats, and how to change a card: [`docs/dashboard.md`](docs/dashboard.md).

## Findings so far

- **Public dashboards:** _link to come after the server cut-over ([`docs/deploy.md`](docs/deploy.md), step 9)._
- [`docs/phase_3_findings.md`](docs/phase_3_findings.md): three investigations, covering disclosed salaries, commercial vs federal skill demand, and field completeness.
- [`docs/findings_commercial_vs_federal_skills.md`](docs/findings_commercial_vs_federal_skills.md): methods note on skill demand by source.
- [`docs/findings_field_completeness.md`](docs/findings_field_completeness.md): which fields measure employer disclosure and which measure our own classifiers.
- [`docs/findings_skill_premium_deferred.md`](docs/findings_skill_premium_deferred.md): why "which skills pay more" isn't answered yet.
- [`docs/phase_1_findings.md`](docs/phase_1_findings.md): what building the pipeline taught.
- [`src/visa/README.md`](src/visa/README.md): the visa-sponsorship layer and what it can't tell you.

## Testing

```bash
uv run pytest                       # unit tests (no services needed)
TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/jobmarket_test \
  uv run pytest                     # + integration tests against real Postgres
uv run ruff check . && uv run ruff format --check .
```

Integration tests drop and recreate the `public` schema, so `tests/conftest.py` refuses any URL whose host isn't `localhost`/`127.0.0.1` or whose database name doesn't contain `test`. Name the driver (`postgresql+psycopg2://`): SQLAlchemy 2.1's default driver for a bare `postgresql://` URL is psycopg 3, which isn't installed.

### SQL views

Views in `sql/views/` are not created by migrations — a fresh `alembic upgrade head` database has none. Apply them (all files, in file-name order, in one transaction, against `DATABASE_URL`):

```bash
make views          # = python scripts/apply_views.py
```

Every file is a single `CREATE OR REPLACE VIEW`, so re-running is safe; re-run after pulling view changes. A view that reads another view must sort after it by file name. Integration tests that need views call `scripts.apply_views.apply_views()` after `reset_schema`.

The integration suite verifies the Phase 1 acceptance criteria directly: end-to-end ingestion, **zero duplicates on re-run**, `first_seen_at` preservation, and the Postgres NULLs-are-distinct location dedup trap.

## Project structure

```
src/
  ingestion/     Adzuna + USAJobs clients, parsers, ingestion, run log, budget guard
  pipeline/      daily runner and health check
  dashboard/     Metabase: read-only role, dashboard spec validator, provisioner, demo dataset
  reports/       Phase 5 report kit: views in, Markdown + PNG charts out, guardrails as code
  cleaning/      Phase 2: normalization & skill extraction
  visa/          visa-sponsorship layer: DOL LCA loader, posting signals, outlook scan (see src/visa/README.md)
  models/        SQLAlchemy models (schema source of truth)
  utils/         config, database session management, secret redaction
migrations/      Alembic (tested in both directions)
notebooks/       numbered analysis notebooks
sql/views/       SQL views: the source of truth for every metric
dashboards/      Metabase dashboards as files (JSON spec + one SQL file per card)
tests/           unit + Postgres integration tests, fixtures
scripts/         smoke test, demo seeder, view loader, daily-run wrappers, Windows scripts
deploy/          server stack: compose, Caddyfile, systemd units, bootstrap, backup/restore/import
Dockerfile       the pipeline image the server runs
docs/            project guide, data dictionary, findings, runbooks
```

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation, schema, Adzuna ingestion, first exploration | ✅ done |
| 2 | Cleaning: company normalization, salary quality, seniority, remote, metro; skill taxonomy and extractor | ✅ done (the extractor matches a curated taxonomy; a spaCy layer is deferred) |
| 3 | Analytics layer: SQL views, investigations | in progress: SQL views and three investigations ([findings](docs/phase_3_findings.md)); the skill salary premium is deferred; investigation notebooks to come |
| — | Second source: USAJobs (federal postings) | ✅ done |
| — | Visa-sponsorship layer: DOL LCA data, posting signals, sponsor matching | ✅ done |
| — | Daily clock: daily runner, run log, Adzuna budget guard, health check, CI | ✅ done (Task Scheduler on the laptop until the server cut-over) |
| 4 | Metabase dashboards | ✅ six dashboards defined as code; public links after the server cut-over |
| 6 | Productionize: scheduling, monitoring, deployment | deploy kit ready ([`docs/deploy.md`](docs/deploy.md)), not yet deployed; scheduling is the daily runner plus a timer, not Prefect |
| 5 | Written reports: the portfolio centerpiece | report kit ready ([`docs/reports.md`](docs/reports.md)): three reports (commercial vs federal skill demand; how much employers disclose; who hires data analysts and who has filed to sponsor them) render their tables, charts and methods from the views with one command; the narrative is next, written on real data |

## Documentation

- [`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md) — full project rationale, architecture, decisions
- [`docs/data_dictionary.md`](docs/data_dictionary.md) — every table, every column, every judgment call
- [`docs/daily-operation.md`](docs/daily-operation.md) — running the daily clock and reading its health check
- [`docs/laptop-runbook.md`](docs/laptop-runbook.md) — the laptop routine (after every pull, weekly) and a troubleshooting table; `python -m src.doctor` checks the setup
- [`docs/dashboard.md`](docs/dashboard.md) — the Metabase dashboards: setup, caveats, changing a card
- [`docs/deploy.md`](docs/deploy.md) — running on a server: bootstrap, cut-over, backups, updating
- [`docs/reports.md`](docs/reports.md) — the written reports: rendering one from the views, the guardrails, writing the narrative
- [`docs/phase_1_findings.md`](docs/phase_1_findings.md) — what Phase 1 revealed about the data
- [`docs/adzuna_sample_response.json`](docs/adzuna_sample_response.json) — API response shape reference
