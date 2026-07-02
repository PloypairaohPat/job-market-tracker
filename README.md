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

Run daily (cron for now; Prefect in Phase 6) to accumulate snapshots:

```cron
15 6 * * *  cd /path/to/job-market-tracker && /path/to/uv run python -m src.ingestion.ingest_adzuna >> logs/ingest.log 2>&1
```

## Testing

```bash
uv run pytest                       # unit tests (no services needed)
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobmarket_test \
  uv run pytest                     # + integration tests against real Postgres
uv run ruff check . && uv run ruff format --check .
```

The integration suite verifies the Phase 1 acceptance criteria directly: end-to-end ingestion, **zero duplicates on re-run**, `first_seen_at` preservation, and the Postgres NULLs-are-distinct location dedup trap.

## Project structure

```
src/
  ingestion/     Adzuna client, parser (pure functions), ingestion pipeline
  cleaning/      Phase 2: normalization & skill extraction
  models/        SQLAlchemy models (schema source of truth)
  utils/         config, database session management
migrations/      Alembic (tested in both directions)
notebooks/       numbered analysis notebooks
sql/views/       Phase 3: SQL views as source of truth for metrics
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
- [`docs/phase_1_findings.md`](docs/phase_1_findings.md) — what Phase 1 revealed about the data
- [`docs/adzuna_sample_response.json`](docs/adzuna_sample_response.json) — API response shape reference
