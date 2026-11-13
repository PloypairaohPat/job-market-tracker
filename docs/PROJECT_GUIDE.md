# Data Analytics Job Market Tracker
## Project guide and interview reference

> A self-hosted analytics platform that ingests live job posting data, extracts skill and salary intelligence, and surfaces trends in the data analytics labor market through dashboards and written analytical reports.

Every claim about the repository on this page names the file that backs it. What was planned and not built is listed separately under [Planned, not built](#planned-not-built), so the original intent isn't lost.

---

## Table of contents
1. [Elevator pitch](#elevator-pitch)
2. [Why this project exists](#why-this-project-exists)
3. [Tech stack](#tech-stack)
4. [Data sources](#data-sources)
5. [Architecture](#architecture)
6. [Database schema](#database-schema)
7. [Phases](#phases)
8. [Planned, not built](#planned-not-built)
9. [Skills demonstrated](#skills-demonstrated)
10. [Interview talking points](#interview-talking-points)
11. [Risks and mitigations](#risks-and-mitigations)
12. [Success metrics](#success-metrics)
13. [Glossary](#glossary)

---

## Elevator pitch

The pitch is yours to write. These are the true, checkable facts it can draw on, with where each is shown.

**For a 30-second version:**

- Two public APIs, ingested daily: Adzuna (commercial postings) and USAJobs (federal postings). `src/ingestion/`, `src/pipeline/daily.py`.
- Every API response is stored verbatim before parsing, so history can be re-parsed. `raw_responses` in `docs/data_dictionary.md`.
- A cleaning layer: company names, salary quality, seniority, remote status, metro, and skill tags from a curated taxonomy. `src/cleaning/`.
- SQL views are the source of truth for every metric. `sql/views/`.
- Six Metabase dashboards defined as code. `dashboards/`, `docs/dashboard.md`.
- Four reports render their tables, charts and methods from the views; the narratives are not written yet. `src/reports/`, `docs/reports.md`.
- Three investigations written up, including one whose clean data refused the original question (the skill salary premium). `docs/phase_3_findings.md`, `docs/findings_skill_premium_deferred.md`.

**For a two-minute version, add:**

- A visa-sponsorship layer joining postings to Department of Labor LCA filing records, kept private at the posting level. `src/visa/README.md`.
- A daily runner with a monthly API budget guard, a run log and a read-only health check; it runs under Windows Task Scheduler today. `docs/daily-operation.md`.
- Guardrails as code: a report can't print a rate without its denominator or a salary median below n = 15. `src/reports/guardrails.py`, `docs/reports.md`.
- CI on every push: lint, format, a migration round trip, the views applied twice and the full test suite against real Postgres. `.github/workflows/ci.yml`.
- A deploy kit for a small server exists and has not been used yet. `docs/deploy.md`.

---

## Why this project exists

### The Problem

Job seekers in data analytics face information asymmetry. Salary bands are often hidden, required skills are described inconsistently across postings, and the "shape" of the market — which skills cluster together, which companies hire most aggressively, how demand evolves month over month — isn't visible from the candidate side. Existing tools like LinkedIn Insights are paywalled and aggregate too high to be useful for tactical career decisions.

### The Goal

Build a transparent, queryable view of the data analytics job market with two simultaneous purposes:

1. **Practical**: produce real insights about the market I'm applying into
2. **Portfolio**: demonstrate the full data analytics workflow end-to-end

### Why It Works as a Portfolio Piece

This project demonstrates the complete analyst lifecycle: **ingestion → cleaning → modeling → analysis → visualization → storytelling**. Every phase produces evidence of a distinct analytical skill, and the final deliverables (dashboard + written reports) are exactly the kinds of outputs an analyst produces on the job. The recursive irony — building an analytics tool to analyze the analytics job market — is a built-in conversation starter in interviews.

### Why Not Just Use Existing Tools

Tools like LinkedIn Insights, Levels.fyi, and Glassdoor exist, but each is locked to a single platform's view, paywalled at the granularity I'd need, or doesn't expose the underlying data for custom analysis. The point of this project isn't to replace those tools — it's to demonstrate the ability to *build* analytical tools from scratch on raw data, which is the actual job of an analyst.

---

## Tech stack

What the repository uses today.

| Layer | Choice | Where |
|---|---|---|
| Language | **Python 3.11+** | `pyproject.toml` |
| Database | **PostgreSQL 16**, JSONB for raw API responses | `docker-compose.yml`, `src/models/` |
| ORM | **SQLAlchemy 2** | `src/models/`, `src/utils/db.py` |
| Migrations | **Alembic**, tested down and up in CI | `migrations/`, `.github/workflows/ci.yml` |
| Skill extraction | **Curated regex taxonomy**: one pattern per skill, precision first, with trap tests | `src/cleaning/data/skills.json`, `src/cleaning/skill_extractor.py` |
| Analysis | **SQL views**, then **pandas** | `sql/views/`, `src/reports/` |
| Exploration | **Jupyter** (one notebook, an optional extra) | `notebooks/01_initial_exploration.ipynb` |
| Charts | **matplotlib** (report charts) | `src/reports/charts.py` |
| BI dashboard | **Metabase**, dashboards as code, read-only database role | `dashboards/`, `src/dashboard/` |
| Scheduling | **The daily runner** under Windows Task Scheduler; a systemd timer in the unused deploy kit | `src/pipeline/daily.py`, `scripts/windows/`, `deploy/systemd/` |
| Containers | **Docker Compose** locally; a pipeline image for the server | `docker-compose.yml`, `Dockerfile` |
| Deployment | **A deploy kit** (compose, Caddy, systemd, backups) for one small server: **not yet used** | `deploy/`, `docs/deploy.md` |
| Tests and CI | **pytest**, **ruff**, **GitHub Actions** | `tests/`, `.github/workflows/ci.yml` |

### Why Python and not TypeScript/Node

My previous project used TypeScript. For analytics work, Python's ecosystem is non-negotiable — pandas, scikit-learn, and Jupyter have no real Node equivalents. Using Python here signals to employers that I select tools for the job rather than defaulting to what I already know.

### Why Metabase and not a custom React dashboard

Most data analyst roles require BI tool fluency (Tableau, Looker, Power BI, Metabase). Building everything in custom React would actually *hurt* the portfolio for analytics roles because it signals "engineer trying to be an analyst." Metabase is free, self-hosted, and demonstrates the right tool selection. A custom React frontend can be added later as an additive layer if useful.

---

## Data sources

### Primary: Adzuna API
- **What it is**: Job aggregator with an official developer API
- **Coverage**: Aggregates postings from across the open web; strong US coverage
- **Free tier**: 1,000 API calls/month (sufficient for daily incremental syncs of targeted searches)
- **Auth**: `app_id` + `app_key` query parameters
- **Docs**: https://developer.adzuna.com/

### Supplemental: USAJobs API
- **What it is**: Official US federal government job board
- **Coverage**: All federal data/analytics roles
- **Free tier**: Unlimited (with reasonable rate-limiting)
- **Auth**: Free API key + email header
- **Why include**: Government roles are absent from most aggregators; adds a sector the dataset would otherwise miss

### Planned, not built: Greenhouse / Lever public boards
Not built. Many companies use Greenhouse or Lever as their applicant tracking system, and the resulting public job board pages are scrape-friendly (predictable URL patterns, structured data in HTML). A scraping layer was planned here; `docs/phase_3_findings.md` names a full-text source like this as the cleaner way to unblock the skill salary premium.

### Why Not LinkedIn / Indeed
LinkedIn's ToS prohibits scraping, their anti-bot detection is aggressive, and the engineering effort to bypass it would consume weeks better spent on actual analysis. Indeed is similar. A portfolio piece shouldn't open with a ToS violation, and the time tradeoff favors using legitimate sources well over scraping illegitimate ones poorly.

### Search queries (`TARGET_QUERIES` in `src/ingestion/ingest_adzuna.py`)
- data analyst
- senior data analyst
- analytics engineer
- business intelligence analyst
- marketing analyst
- product analyst

"Data Scientist" was planned as a comparison query and is not in the list. USAJobs adds keyword queries and three occupational series (1560, 1515, 1530; `docs/daily-operation.md`).

### Geographies
US-wide. The tracked metro list (`src/cleaning/metro.py`) is NYC, SF Bay Area, LA, Chicago, Boston, Seattle, Austin and DC; remote is a separate flag (`jobs.is_remote`), not a metro.

---

## Architecture

The diagram in the [README](../README.md#how-it-works) is the current one. In words:

1. **Sources.** Adzuna and USAJobs APIs, called by the daily runner; DOL LCA disclosure files, loaded by hand (`src/visa/lca_loader.py`).
2. **Raw.** Every response is stored verbatim in `raw_responses` before parsing.
3. **Core tables.** `jobs`, `companies`, `locations`, and `job_snapshots` (one row per job per UTC day it was returned).
4. **Enrichment.** Cleaning (`src/cleaning/apply_cleaning.py`), skills (`src/cleaning/extract_skills.py`) and visa signals (`src/visa/posting_signals.py`), run by the daily runner after ingestion.
5. **Views.** `sql/views/v_*`, the source of truth for every metric.
6. **Outputs.** Metabase dashboards (read-only role) and the report kit (`src/reports/`).

### Key architectural decisions

**Raw-then-normalized pattern**: Every API response is stored as JSONB in `raw_responses` *before* being parsed into normalized tables. Schema changes and parser fixes don't require re-fetching from the API: `python -m src.ingestion.ingest_usajobs --backfill-from-raw` re-parses stored responses.

**Idempotent ingestion**: Jobs are keyed by `(source, external_id)`, so re-running the sync never creates duplicates and always brings the dataset to the latest state (`tests/test_ingestion.py`).

**Daily snapshots, not just current state**: `job_snapshots` records each job on each UTC day the search returned it. This is what will enable time-series analysis once enough days accumulate; what it can and can't support is in `docs/data_dictionary.md`.

**Analytics in SQL first, Python second**: SQL views are the source of truth for derived metrics. The report kit reads whole views only (`src/reports/views.py`), so the dashboards and reports stay consistent.

---

## Database schema

The schema is defined by the SQLAlchemy models in `src/models/` and the Alembic migrations in `migrations/`; every column and judgment call is in [`docs/data_dictionary.md`](data_dictionary.md). The tables:

| Table | One row per |
|---|---|
| `raw_responses` | API response, stored verbatim (JSONB) |
| `companies` | employer as the source names it, with `normalized_name` for grouping variants |
| `locations` | (city, state, country), with `metro_area` from a tracked list |
| `jobs` | posting, keyed by `(source, external_id)`, with cleaned fields (seniority, salary quality, remote, scope) |
| `job_snapshots` | job per UTC day it was returned |
| `skills`, `job_skills` | taxonomy skill; job-skill link with a confidence |
| `job_visa_signals` | job's visa-related posting signals |
| `lca_cases` | DOL LCA filing, loaded from disclosure files |
| `ingestion_runs` | ingestion run per source (the run log) |

---

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation, schema, Adzuna ingestion, first exploration | done (`docs/phase_1_findings.md`) |
| 2 | Cleaning: company normalization, salary quality, seniority, remote, metro; skill taxonomy and extractor | done; the extractor is a curated regex taxonomy |
| 3 | SQL views and investigations | three investigations written up (`docs/phase_3_findings.md`); the skill salary premium is deferred |
| — | Second source (USAJobs), visa-sponsorship layer, daily clock | done |
| 4 | Metabase dashboards | six dashboards defined as code; public links after the server cut-over |
| 5 | Written reports | the report kit renders four reports from the views; the narratives are not written |
| 6 | Productionize | the daily runner, health check and CI exist; the deploy kit has not been used |

---

## Planned, not built

Kept so the original plan stays visible. None of these exists in the repository.

- **spaCy skill extraction.** Planned for Phase 2; deferred. Extraction is the regex taxonomy above.
- **Prefect orchestration.** Planned for Phase 6; not used. Scheduling is the daily runner under Task Scheduler (and a systemd timer in the deploy kit).
- **Running on a Hetzner VPS.** The deploy kit targets a small server like this; it has not been deployed.
- **Skill salary premium** ("which skills pay more"). Attempted in Phase 3 and deferred: the clean data couldn't support it (`docs/findings_skill_premium_deferred.md`).
- **Greenhouse / Lever scraping**, a custom React frontend, skill co-occurrence clustering, a salary prediction model, and the remaining stretch goals under [Success metrics](#success-metrics).
- **Phase 3 investigation notebooks.** The investigations live in SQL views and findings docs; the only notebook is the Phase 1 exploration.

---

## Skills demonstrated

Each bullet names where it is shown.

### Technical

- **SQL**: views with CTEs, window functions and multi-table joins as the source of truth for every metric (`sql/views/`).
- **Python analytics stack**: pandas for the report kit's computations (`src/reports/`).
- **Text extraction**: a curated regex skill taxonomy with precision-first patterns and trap tests (`src/cleaning/skill_extractor.py`, `tests/`).
- **Data modeling**: a normalized Postgres schema with daily snapshots (`src/models/`, `docs/data_dictionary.md`).
- **ETL design**: idempotent ingestion keyed by `(source, external_id)`, raw-then-normalized storage, and replay from raw responses (`src/ingestion/`).
- **Data cleaning**: company name normalization with fuzzy merge candidates for manual review, salary quality flags, seniority from titles, metro assignment (`src/cleaning/`).
- **BI tools**: six Metabase dashboards defined as code and provisioned through the API (`dashboards/`, `src/dashboard/`).
- **Statistical reporting discipline**: medians with IQR, n beside every grouped number, floors below which a figure is withheld (`src/reports/guardrails.py`).
- **Data visualization**: matplotlib report charts (`src/reports/charts.py`) and Metabase cards.
- **Scheduling and monitoring**: a daily runner with a budget guard, run log, health check and laptop doctor (`src/pipeline/`, `src/doctor.py`).
- **Containers and CI**: Docker Compose, a pipeline image checked by `scripts/verify_image.sh`, GitHub Actions running lint, format, a migration round trip, the views applied twice and the test suite.
- **Version control**: a public GitHub repo with documentation.

### Analytical

- Framing vague questions as answerable investigations, and recording when the data refuses one (`docs/phase_3_findings.md`, Investigation #1).
- Separating measured fields from instrument-limited ones (`docs/findings_field_completeness.md`).
- Recognizing data quality issues and documenting their effect on conclusions (`docs/phase_1_findings.md`, `docs/findings_commercial_vs_federal_skills.md`).
- Tradeoff thinking, for example data freshness vs API limits (the budget guard in `docs/daily-operation.md`).

---

## Interview talking points

Prompts for your own answers. Under each question are the facts and files you can draw on; the answers are yours to write.

### "Tell me about a data project you've built."

- Start from the elevator-pitch facts above, then offer to go deeper on one part.

### "What was the hardest part?"

Candidates, each documented:

- The skill salary premium the clean data couldn't support, and why: too few disclosed salaries carry skill tags, and pooling Adzuna's predicted salaries would make the premium partly Adzuna's own model (`docs/phase_3_findings.md`, Investigation #1).
- Truncated commercial descriptions (Adzuna's ~500 characters) vs full federal text, and why a truncation-matched comparison was dropped (`docs/phase_3_findings.md`, Investigation #2).
- Two "built but never run" capabilities found in Phase 3: the USAJobs series-code ingest and taxonomy gaps (`docs/phase_3_findings.md`, "Prep that made the investigation valid").
- Company name normalization: deterministic normalization plus fuzzy merge candidates written to a CSV for manual review, never auto-merged (`src/cleaning/README.md`, `src/cleaning/company_normalizer.py`).

### "How did you handle messy data?"

- Raw before normalized: `raw_responses` (`docs/data_dictionary.md`).
- Every cleaning decision documented in `docs/data_dictionary.md`.
- Flag, don't guess: no signal means NULL, never a default bucket; `salary_quality` flags instead of guessed salaries (`src/cleaning/README.md`, design rule 1).

### "What insights did you find?"

- The figures in the README's "Findings so far" section, quoted from `docs/phase_3_findings.md` with their n.
- The published reports, once their narratives are written (`docs/reports.md`).

### "Walk me through your tech stack choices."

- The tech stack table above, and the three architectural decisions.

### "What would you do differently?"

- The parked decisions in each work log under `docs/dev-log/` and the open threads in `docs/phase_3_findings.md` are the documented candidates.

### "How does this scale?"

- Facts to start from: daily volume is a few hundred postings per source (`docs/daily-operation.md`); `raw_responses` and `job_snapshots` grow every day; the report kit reads whole views (`src/reports/views.py`).

### "What did you learn?"

- Material: `docs/phase_1_findings.md` and the "Why" sections of each Phase 3 investigation.

---

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Adzuna rate limits hit too early | Medium | High | Cache aggressively; pre-compute target searches; supplement with USAJobs |
| Skill extraction has poor precision | High | Medium | A curated regex taxonomy with precision-first patterns and a trap test per ambiguous pattern (built); spaCy patterns were planned and deferred |
| Company name normalization is too lossy | High | Medium | Keep raw names always; build normalization as a *layer*, not a destructive transform |
| Project scope creeps | High | High | Strict phase gates with written acceptance criteria; resist new features until current phase ships |
| Data volume too small for time-series analysis | Medium | Medium | Gate Phase 3 time-series work on having 60+ days of snapshots accumulated |
| I lose interest mid-project | Medium | Very High | Make Phase 5 (writing reports) something I'm genuinely curious about; the project survives if the writing survives |

---

## Success metrics

### Project is "done enough for portfolio" when:
- [ ] 10,000+ unique jobs in database
- [ ] 90+ days of historical snapshots
- [ ] Metabase dashboard publicly accessible (read-only)
- [ ] At least 3 written reports published (blog or GitHub)
- [ ] Public GitHub repo with thorough README
- [ ] Daily ingestion has been running automatically for 60+ days
- [ ] Can be explained start-to-finish in under 3 minutes

### Stretch goals
- [ ] Custom React frontend layered on top of Metabase
- [ ] Salary prediction model (regression on skill set + location + seniority)
- [ ] Skill embedding visualization (which skills cluster?)
- [ ] Browser extension that overlays "market context" on LinkedIn job pages

---

## Glossary

- **Adzuna**: Public job aggregator with developer API used as primary data source
- **Idempotent ingestion**: Pipeline design where re-running the same sync produces the same end state (no duplicates)
- **JSONB**: PostgreSQL's binary JSON column type — supports indexing and querying inside JSON values
- **LCA**: Labor Condition Application, the Department of Labor filing an employer makes before an H-1B petition (`src/visa/README.md`)
- **Metabase**: Open-source business intelligence tool; like Tableau but free and self-hosted
- **Normalization (data)**: Cleaning raw values into canonical forms (e.g., 'Meta Platforms Inc' → 'Meta')
- **Raw-then-normalized**: Pattern of storing API responses verbatim before parsing, enabling schema evolution without re-fetching
- **Snapshot**: A record of a job on a day the search returned it; enables time-series analysis
