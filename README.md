# Job Market Tracker

A self-hosted analytics platform that ingests live job posting data, extracts skill and salary intelligence, and surfaces trends in the data analytics labor market through dashboards and written analytical reports.

## Findings so far

From the three Phase 3 investigations in [`docs/phase_3_findings.md`](docs/phase_3_findings.md) (as of 2026-09-03), quoted as written there:

- **What commercial postings pay.** Among commercial (Adzuna) data-analyst postings with an employer-disclosed annual USD salary, the median salary midpoint is **$98,500** (IQR $87,013–$111,425; n=178).
- **Who discloses salary.** Employer-disclosed salary appears on **12.1%** of commercial postings (180 of n=1,483) and **100.0%** of federal in-scope postings (n=70).
- **What the two markets ask for.** Of each market's own skill tags (confidence ≥ 0.8), commercial skews **workflow + bi_tool** (56.7% combined; n=1,483 jobs) and federal skews **ml_stats + language** (67.0% combined; n=70 jobs). Commercial skill rates are truncation-floored (Adzuna's ~500-character descriptions).

Methods and caveats behind each figure: [`docs/findings_commercial_vs_federal_skills.md`](docs/findings_commercial_vs_federal_skills.md), [`docs/findings_field_completeness.md`](docs/findings_field_completeness.md), [`docs/findings_skill_premium_deferred.md`](docs/findings_skill_premium_deferred.md) (why "which skills pay more" isn't answered yet), [`docs/phase_1_findings.md`](docs/phase_1_findings.md) (what building the pipeline taught), and [`src/visa/README.md`](src/visa/README.md) (the visa-sponsorship layer and what it can't tell you).

## Published reports

<!-- published-reports:start -->
The reports are rendered from the SQL views and published here as each narrative is written; see [docs/reports.md](docs/reports.md).
<!-- published-reports:end -->

## Dashboards

Six Metabase dashboards are defined as files in `dashboards/`: ingestion health, market overview, salary, skills, transparency, and a private visa outlook. They read only the `v_*` SQL views, through a read-only database role. Public links will follow the server cut-over ([`docs/deploy.md`](docs/deploy.md)); until then they run locally ([`docs/dashboard.md`](docs/dashboard.md)).

## In three minutes

I built a job-market analytics platform for data-analyst roles. Every day it pulls postings from two public APIs: Adzuna for commercial jobs and USAJobs for federal ones. It stores every raw response in Postgres, so history can be replayed. Then it cleans the messy parts: company names, salary formats, locations, seniority, remote status and skill mentions.

SQL views are the single source of truth for every metric. Grouped numbers sit next to their n, with their caveats.

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

Python 3.11+ · PostgreSQL 16 · SQLAlchemy 2 · Alembic · pandas · matplotlib · Metabase · Docker Compose · pytest · ruff · GitHub Actions (Jupyter for the notebooks; Caddy and systemd in the unused deploy kit).

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

## Run it yourself

**Prerequisites**: Docker, Python 3.11+, and [`uv`](https://docs.astral.sh/uv/) (or plain `pip`).

```bash
git clone https://github.com/PloypairaohPat/job-market-tracker.git
cd job-market-tracker
cp .env.example .env               # API credentials go here (real-data path only)
docker compose up -d               # Postgres 16 on localhost:5432
uv sync                            # or: pip install -e ".[dev]"
```

**With synthetic demo data (no API key).** The full demo seed truncates its target, so it runs only against a database whose name contains `demo` or `test`:

```bash
docker compose exec db createdb -U postgres jobmarket_demo
export DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/jobmarket_demo
uv run alembic upgrade head
uv run python scripts/seed_demo_data.py --full         # both markets, four weeks of snapshots; applies the views
uv run python -m src.reports how-much-employers-disclose   # renders reports/<slug>/ with the demo banner
```

**With real data.** Register free for [Adzuna](https://developer.adzuna.com/) (1,000 calls/month; the runner enforces a monthly budget) and [USAJobs](https://developer.usajobs.gov/APIRequest/), put the credentials in `.env`, then:

```bash
uv run alembic upgrade head
uv run python scripts/smoke_adzuna.py      # one API call: are the credentials right?
uv run python -m src.pipeline.daily        # both sources, cleaning, skills, health check
uv run python scripts/apply_views.py       # the SQL views (make views)
```

Running it every day, reading the health check and the budget arithmetic: [`docs/daily-operation.md`](docs/daily-operation.md). The exploration notebook needs the `notebook` extra: `uv run --extra notebook jupyter lab notebooks/01_initial_exploration.ipynb`.

**Tests.** `uv run pytest` runs the unit tests; set `TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/jobmarket_test` to add the integration tests against real Postgres. They drop and recreate the `public` schema, so `tests/conftest.py` refuses any URL whose host isn't `localhost`/`127.0.0.1` or whose database name doesn't contain `test`. The integration suite checks end-to-end ingestion, zero duplicates on re-run, `first_seen_at` preservation and the NULLs-are-distinct location dedup trap. Lint with `uv run ruff check . && uv run ruff format --check .`.

**SQL views.** Views in `sql/views/` are not created by migrations. `make views` (`python scripts/apply_views.py`) applies every file in file-name order, in one transaction; each is a single `CREATE OR REPLACE VIEW`, so re-running is safe. A view that reads another view must sort after it by file name. More in [`sql/views/README.md`](sql/views/README.md).

## Status

| Built | In progress | Not started |
|---|---|---|
| Adzuna and USAJobs ingestion, every raw response stored | Daily collection: the clock runs on a laptop under Task Scheduler and has missed days | Server deployment: the deploy kit ([`docs/deploy.md`](docs/deploy.md)) exists and has not been used |
| Daily runner with a budget guard, run log, health check and laptop doctor | Phase 3 analysis: three investigations written up; the skill salary premium is deferred | Report narratives: none of the four is written, so nothing is published yet |
| Cleaning layer, skill taxonomy extractor, visa-sponsorship layer | | Public dashboard links (they follow the server cut-over) |
| SQL views, six Metabase dashboards as code | | |
| Report kit: four reports render from the views; a publish path for the narratives | | |
| CI: lint, format, migration round trip and the full test suite | | |

## Documentation

- [`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md) — project rationale, architecture, decisions
- [`docs/data_dictionary.md`](docs/data_dictionary.md) — every table, every column, every judgment call
- [`docs/daily-operation.md`](docs/daily-operation.md) — running the daily clock and reading its health check
- [`docs/laptop-runbook.md`](docs/laptop-runbook.md) — the laptop routine (after every pull, weekly) and a troubleshooting table; `python -m src.doctor` checks the setup
- [`docs/dashboard.md`](docs/dashboard.md) — the Metabase dashboards: setup, caveats, changing a card
- [`docs/deploy.md`](docs/deploy.md) — running on a server: bootstrap, cut-over, backups, updating
- [`docs/time-series-readiness.md`](docs/time-series-readiness.md) — what the daily snapshots can and can't support, and the checks to run before trusting a trend
- [`docs/reports.md`](docs/reports.md) — the written reports: rendering, the guardrails, writing and publishing the narrative
- [`docs/phase_1_findings.md`](docs/phase_1_findings.md) — what Phase 1 revealed about the data
- [`docs/dev-log/`](docs/dev-log/README.md) — work logs from AI-assisted build sessions
- [`docs/adzuna_sample_response.json`](docs/adzuna_sample_response.json) — API response shape reference
- [`LICENSE`](LICENSE) — MIT
