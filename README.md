# Job Market Tracker

A self-hosted analytics platform that ingests live job posting data, extracts skill and salary intelligence, and surfaces trends in the data analytics labor market through dashboards and written analytical reports.

**Why it exists**: job seekers in analytics face information asymmetry — hidden salary bands, inconsistent skill descriptions, no visibility into market shape. This project builds a transparent, queryable view of that market, and in doing so demonstrates the full analyst workflow: **ingestion → cleaning → modeling → analysis → visualization → storytelling**.

> **Status: Phase 1 complete** — foundation, schema, Adzuna ingestion pipeline, and initial exploration. See [`docs/phase_1_findings.md`](docs/phase_1_findings.md) and the [roadmap](#roadmap).

## How it works

```
Adzuna API ──▶ Ingestion ──▶ raw_responses (JSONB, verbatim)
                                   │
                                   ▼
                        Cleaning + parsing pipeline
                                   │
                                   ▼
              jobs · companies · locations · job_snapshots
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
      Jupyter notebooks    Metabase dashboard    Written reports
       (exploration)        (Phase 4)             (Phase 5)
```

Three architectural decisions carry the design:

1. **Raw-then-normalized** — every API response is stored verbatim as JSONB *before* parsing. Parsing bugs and schema changes are fixed by replaying history, never by re-fetching.
2. **Idempotent ingestion** — jobs are keyed by `(source, external_id)`; re-running a sync never duplicates data and always converges on the latest observed state. Verified by integration tests against real Postgres.
3. **Daily snapshots from day one** — `job_snapshots` records each job's observed state per day, so time-series analysis (posting lifetimes, salary changes, demand shifts) becomes possible the moment enough days accumulate.

## Tech stack

Python 3.11+ · PostgreSQL 16 · SQLAlchemy 2.0 · Alembic · pandas · Plotly · Jupyter · Docker Compose · pytest · ruff — with spaCy (skill extraction), Metabase (BI), and Prefect (orchestration) arriving in later phases. Rationale for every choice is in [`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md).

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

## Daily operation

The portfolio targets (90+ days of snapshots, 60+ days of daily ingestion, 10,000+ jobs) only accumulate if ingestion fires every day, and a missed day can never be backfilled. One command runs the whole day, both sources, then cleaning, skills and a health check, with a dated log and the monthly Adzuna budget enforced:

```bash
uv run python -m src.pipeline.daily      # or: make daily
uv run python -m src.pipeline.health     # is the clock running? exit 1 on any FAIL (make health)
```

On Windows, `scripts/windows/register_daily_task.ps1` registers it as a daily scheduled task; on Linux, `scripts/run_daily.sh` is the cron entry point. Setup, what each health check means, and the budget arithmetic: [`docs/daily-operation.md`](docs/daily-operation.md).

## Dashboard

Six Metabase dashboards (ingestion health, market overview, salary, skills, transparency, and a private visa outlook) are defined as files in `dashboards/`. They read only the `v_*` SQL views, through a read-only database role. Metabase runs in an opt-in compose profile:

```bash
uv run python -m src.dashboard.reader_role   # read-only role (make bi-grant)
docker compose --profile bi up -d            # Metabase on http://localhost:3000 (make bi-up)
uv run python -m src.dashboard.provision     # build/refresh every dashboard (make bi-provision)
```

Setup, what each dashboard shows and its caveats, and how to change a card: [`docs/dashboard.md`](docs/dashboard.md).

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
  cleaning/      Phase 2: normalization & skill extraction
  visa/          visa-sponsorship layer: DOL LCA loader, posting signals, outlook scan (see src/visa/README.md)
  models/        SQLAlchemy models (schema source of truth)
  utils/         config, database session management
migrations/      Alembic (tested in both directions)
notebooks/       numbered analysis notebooks
sql/views/       SQL views: the source of truth for every metric
dashboards/      Metabase dashboards as files (JSON spec + one SQL file per card)
tests/           unit + Postgres integration tests, fixtures
scripts/         smoke test, demo seeder
docs/            project guide, data dictionary, phase findings
```

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation, schema, Adzuna ingestion, first exploration | ✅ complete |
| 2 | Cleaning: company normalization, salary parsing, spaCy skill extraction | next |
| 3 | Analytics layer: SQL views, investigation notebooks | |
| 4 | Metabase dashboards | |
| 5 | Written reports — the portfolio centerpiece | |
| 6 | Prefect orchestration, quality monitoring, Hetzner deployment | |

## Documentation

- [`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md) — full project rationale, architecture, decisions
- [`docs/data_dictionary.md`](docs/data_dictionary.md) — every table, every column, every judgment call
- [`docs/daily-operation.md`](docs/daily-operation.md) — running the daily clock and reading its health check
- [`docs/dashboard.md`](docs/dashboard.md) — the Metabase dashboards: setup, caveats, changing a card
- [`docs/phase_1_findings.md`](docs/phase_1_findings.md) — what Phase 1 revealed about the data
- [`docs/adzuna_sample_response.json`](docs/adzuna_sample_response.json) — API response shape reference
