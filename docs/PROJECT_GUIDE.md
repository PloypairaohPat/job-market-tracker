# Data Analytics Job Market Tracker
## Project Guide & Interview Reference

> A self-hosted analytics platform that ingests live job posting data, extracts skill and salary intelligence, and surfaces trends in the data analytics labor market through a dashboard and written analytical reports.

---

## Table of Contents
1. [Elevator Pitch](#elevator-pitch)
2. [Why This Project Exists](#why-this-project-exists)
3. [Tech Stack](#tech-stack)
4. [Data Sources](#data-sources)
5. [Architecture](#architecture)
6. [Database Schema (v1)](#database-schema-v1)
7. [Phased Roadmap](#phased-roadmap)
8. [Skills Demonstrated](#skills-demonstrated)
9. [Interview Talking Points](#interview-talking-points)
10. [Risks & Mitigations](#risks--mitigations)
11. [Success Metrics](#success-metrics)
12. [Glossary](#glossary)

---

## Elevator Pitch

**30-second version (for recruiter screens):**

> "I built a job market analytics platform that pulls thousands of data analytics job postings from public APIs, normalizes the messy real-world data — company names, salary formats, locations, skill mentions — and surfaces insights about which skills carry salary premiums, how demand shifts over time, and where the strongest hiring markets are. It runs a daily ingestion job, stores everything in Postgres, and presents the analysis through a Metabase dashboard and a series of written reports. I built it because I wanted to understand the market I'm entering — and to demonstrate the full analyst workflow end-to-end."

**Two-minute version (for technical conversations):**

> "It's a Python-based data pipeline and analytics platform built around a single question: what does the data analytics job market actually look like, quantitatively? I ingest job postings daily from Adzuna and USAJobs, store raw responses in Postgres for replay-ability, then run a cleaning pipeline that normalizes companies, parses salary ranges, standardizes locations, and extracts skills from job descriptions using spaCy. On top of that sits an analytics layer — SQL views, Jupyter investigations, and a Metabase dashboard — that surfaces things like skill-salary correlations, geographic demand patterns, and how the market shifts over time. The whole stack runs on a Hetzner VPS with Prefect for orchestration. The deliverables are the dashboard plus a series of written reports answering specific market questions. The reports are arguably the most important part — they're what an analyst actually produces, and they're what differentiates this from a pure engineering project."

---

## Why This Project Exists

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

## Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | **Python 3.11+** | Industry standard for analytics; rich ecosystem (pandas, spaCy, scikit-learn) |
| Database | **PostgreSQL 16** | Mature, JSONB support for raw API responses, strong analytics SQL features |
| ORM | **SQLAlchemy 2.0** | Professional standard; type-safe; declarative models |
| Migrations | **Alembic** | Reversible migrations, integrates with SQLAlchemy |
| NLP | **spaCy** | Production-grade skill extraction without ML training complexity |
| Analysis | **pandas, numpy, Jupyter** | Notebook-driven analysis is the analyst's primary workflow |
| Visualization | **Plotly + matplotlib** | Plotly for interactive, matplotlib for publication-quality figures |
| BI Dashboard | **Metabase** | Free, self-hosted, used by real companies — table-stakes BI exposure |
| Orchestration | **Prefect** (cron initially) | Schedule daily ingestion, monitor failures, retry on errors |
| Container | **Docker + Docker Compose** | Reproducible local dev, clean deploys |
| Deployment | **Hetzner VPS** | Self-hosted, full control, ~€4/month |
| Version Control | **Git + GitHub** | Public repo as portfolio artifact |

### Why Python and not TypeScript/Node

My previous project used TypeScript. For analytics work, Python's ecosystem is non-negotiable — pandas, spaCy, scikit-learn, and Jupyter have no real Node equivalents. Using Python here signals to employers that I select tools for the job rather than defaulting to what I already know.

### Why Metabase and not a custom React dashboard

Most data analyst roles require BI tool fluency (Tableau, Looker, Power BI, Metabase). Building everything in custom React would actually *hurt* the portfolio for analytics roles because it signals "engineer trying to be an analyst." Metabase is free, self-hosted, and demonstrates the right tool selection. A custom React frontend can be added later as an additive layer if useful.

---

## Data Sources

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

### Optional (Phase 3+): Greenhouse / Lever Public Boards
Many companies use Greenhouse or Lever as their applicant tracking system, and the resulting public job board pages are scrape-friendly (predictable URL patterns, structured data in HTML). Adding a scraping layer here demonstrates web scraping skills without crossing any ToS lines.

### Why Not LinkedIn / Indeed
LinkedIn's ToS prohibits scraping, their anti-bot detection is aggressive, and the engineering effort to bypass it would consume weeks better spent on actual analysis. Indeed is similar. A portfolio piece shouldn't open with a ToS violation, and the time tradeoff favors using legitimate sources well over scraping illegitimate ones poorly.

### Target Roles (Initial Search Queries)
- Data Analyst
- Senior Data Analyst
- Analytics Engineer
- Business Intelligence Analyst
- Marketing Analyst
- Product Analyst
- Data Scientist (for comparison / seniority crossover)

### Target Geographies (Phase 1)
US-wide via Adzuna, with focus on major metros for cross-comparison: NYC, SF Bay Area, LA, Chicago, Boston, Seattle, Austin, Remote.

---

## Architecture

```
┌─────────────────┐
│  Adzuna API     │──┐
└─────────────────┘  │
                     │  ┌──────────────────┐    ┌─────────────────────┐
┌─────────────────┐  ├─▶│  Ingestion       │───▶│ raw_responses       │
│  USAJobs API    │──┤  │  (Python + Prefect)│  │ (JSONB)             │
└─────────────────┘  │  └──────────────────┘    └──────────┬──────────┘
                     │                                     │
┌─────────────────┐  │                                     ▼
│ Greenhouse/Lever│──┘                          ┌──────────────────────┐
│ (optional)      │                             │  Cleaning + NLP      │
└─────────────────┘                             │  pipeline            │
                                                │  (pandas + spaCy)    │
                                                └──────────┬───────────┘
                                                           │
                                                           ▼
                                                ┌──────────────────────┐
                                                │  Normalized tables   │
                                                │  jobs, companies,    │
                                                │  skills, locations   │
                                                └──────────┬───────────┘
                                                           │
                            ┌──────────────────────────────┼───────────────────────────┐
                            ▼                              ▼                           ▼
                ┌────────────────────┐         ┌────────────────────┐    ┌────────────────────┐
                │  Jupyter notebooks │         │  Metabase dashboard│    │  Written reports   │
                │  (exploration)     │         │  (interactive BI)  │    │  (the storytelling)│
                └────────────────────┘         └────────────────────┘    └────────────────────┘
```

### Key Architectural Decisions

**Raw-then-normalized pattern**: Every API response is stored as JSONB in `raw_responses` *before* being parsed into normalized tables. This means schema changes don't require re-fetching from the API — I can re-parse historical raw responses. This pattern is borrowed directly from my finance dashboard project where it proved invaluable.

**Idempotent ingestion**: The ingestion script uses each job's external ID as a natural key, so re-running the sync never creates duplicates and always brings the dataset to the latest state.

**Daily snapshots, not just current state**: A `job_snapshots` table records the state of every job each day it's observed. This is what enables time-series analysis (when did a job appear/disappear, did the salary change, etc.).

**Analytics in SQL first, Python second**: SQL views are the source of truth for derived metrics. Python notebooks pull from those views rather than reimplementing logic. This keeps the dashboard and notebooks consistent.

---

## Database Schema (v1)

### Core Tables

**`raw_responses`** — every API call result, stored verbatim
```
id              SERIAL PRIMARY KEY
source          TEXT  -- 'adzuna' | 'usajobs' | 'greenhouse'
fetched_at      TIMESTAMPTZ
endpoint        TEXT
params          JSONB
response        JSONB
```

**`companies`** — normalized company entity
```
id              SERIAL PRIMARY KEY
canonical_name  TEXT UNIQUE  -- e.g., 'Meta'
raw_names       TEXT[]       -- ['Facebook', 'Meta Platforms Inc', 'FB']
industry        TEXT
size_bucket     TEXT          -- '1-50' | '51-200' | etc.
created_at      TIMESTAMPTZ
```

**`locations`** — normalized location
```
id              SERIAL PRIMARY KEY
city            TEXT
state           TEXT
country         TEXT
metro_area      TEXT          -- 'NYC' | 'SF Bay Area' | etc.
is_remote       BOOLEAN
latitude        DECIMAL
longitude       DECIMAL
```

**`jobs`** — one row per unique job posting
```
id                  SERIAL PRIMARY KEY
external_id         TEXT UNIQUE   -- ID from source system
source              TEXT
company_id          INT REFERENCES companies
location_id         INT REFERENCES locations
title               TEXT
title_normalized    TEXT          -- 'data analyst' (lowercased, cleaned)
seniority           TEXT          -- 'junior' | 'mid' | 'senior' | 'lead'
description         TEXT
salary_min          INT
salary_max          INT
salary_currency     TEXT
salary_period       TEXT          -- 'year' | 'hour' | 'month'
is_remote           BOOLEAN
posted_at           TIMESTAMPTZ
first_seen_at       TIMESTAMPTZ
last_seen_at        TIMESTAMPTZ
removed_at          TIMESTAMPTZ NULL
raw_response_id     INT REFERENCES raw_responses
```

**`skills`** — skill taxonomy
```
id              SERIAL PRIMARY KEY
name            TEXT UNIQUE   -- 'Python', 'SQL', 'Tableau'
category        TEXT          -- 'language' | 'tool' | 'cloud' | 'soft'
aliases         TEXT[]        -- ['py'] for Python
```

**`job_skills`** — many-to-many
```
job_id          INT REFERENCES jobs
skill_id        INT REFERENCES skills
confidence      DECIMAL       -- extraction confidence 0–1
PRIMARY KEY (job_id, skill_id)
```

**`job_snapshots`** — daily state for time-series analysis
```
id              SERIAL PRIMARY KEY
job_id          INT REFERENCES jobs
snapshot_date   DATE
is_active       BOOLEAN
salary_min      INT
salary_max      INT
PRIMARY KEY (job_id, snapshot_date)
```

This schema will evolve through Alembic migrations. Phase 1 only requires `raw_responses`, `companies`, `locations`, and `jobs`.

---

## Phased Roadmap

### Phase 1 — Foundation & First Ingestion (2–3 weeks)
Set up project, Postgres, schema v1, Adzuna client, first ingestion of 1,000+ jobs, initial Jupyter exploration. *See separate `PHASE_1_MILESTONE.md` for step-by-step.*

### Phase 2 — Cleaning & Skill Extraction (2–3 weeks)
Company name normalization, salary parsing, location standardization, skill taxonomy construction, spaCy-based skill extraction from job descriptions, seniority classification. **This is the analyst-defining phase** — document every cleaning decision because *that* is the portfolio.

### Phase 3 — Analytics Layer (3–4 weeks)
SQL views for all key metrics. Jupyter notebook portfolio with investigations: skill co-occurrence networks, salary distributions by skill/location/seniority, hiring velocity, geographic patterns. Each notebook is publication-quality.

### Phase 4 — Dashboard (3–4 weeks)
Metabase deployment. Build dashboards: market overview, skill explorer, salary analyzer, geographic view, company leaderboard. Optionally embed in a custom React landing page.

### Phase 5 — Storytelling (2–3 weeks)
Pick 3–5 sharp analytical questions and write them up as blog posts or a report:
- *Which skills carry the biggest salary premium for data analysts?*
- *How has AI/ML demand shifted in analyst roles over [N] months?*
- *Remote vs onsite salary delta by metro area*
- *What kinds of "data analyst" roles actually exist? (skill-based clustering)*
- *Which companies hire the most aggressively, and what are they looking for?*

These reports are the portfolio centerpiece.

### Phase 6 — Productionize (2 weeks)
Prefect orchestration, data quality monitoring, public deployment to Hetzner, README polish, automated tests, public GitHub repo finalization.

**Total estimated duration: 5–6 months**

---

## Skills Demonstrated

### Technical Skills (resume-ready bullets)

- **SQL**: Complex queries with CTEs, window functions, joins across 6+ tables; SQL views as source of truth for analytics
- **Python (analytics stack)**: pandas, numpy, Jupyter for data wrangling and analysis
- **NLP**: spaCy for skill extraction from unstructured job descriptions
- **Data modeling**: Designed normalized PostgreSQL schema supporting both current-state queries and historical time-series analysis
- **ETL pipeline design**: Idempotent ingestion with raw-then-normalized pattern; daily snapshots for change tracking
- **Data cleaning**: Real-world messy data — company name deduplication, multi-format salary parsing, location standardization
- **BI tools**: Metabase dashboard design and deployment
- **Statistical analysis**: Distribution analysis, correlation, cohort analysis, basic clustering
- **Data visualization**: Plotly, matplotlib, Metabase
- **Orchestration**: Prefect for scheduled ingestion and monitoring
- **Production deployment**: Docker, self-hosted on Hetzner VPS
- **Version control**: Git, public GitHub repo with documentation

### Analytical Skills

- Framing vague questions as answerable analytical investigations
- Choosing appropriate visualizations for different question types
- Communicating quantitative findings in writing for non-technical audiences
- Recognizing data quality issues and documenting their impact on conclusions
- Tradeoff thinking (e.g., data freshness vs. API rate limits)

---

## Interview Talking Points

### "Tell me about a data project you've built."

> *Start with the elevator pitch above, then offer to go deeper on any specific aspect.* The interviewer's follow-up will tell you what they care about — technical depth, business impact, or methodology.

### "What was the hardest part?"

> "Company name normalization. The raw data had 'Meta', 'Meta Platforms Inc.', 'Facebook', and 'FB' all referring to the same employer, and that's an easy case. The harder cases were small companies with regional subsidiaries, name changes over time, and recruiting agencies posting on behalf of unnamed clients. I ended up with a hybrid approach: deterministic rules for the obvious cases, fuzzy matching with manual review for ambiguous ones, and a `raw_names` array on the companies table so I never lose the source-of-truth strings."

### "How did you handle messy data?"

> "Three principles. First, always store raw before normalized — every API response goes into a `raw_responses` table as JSONB before any parsing, so I can re-run cleaning logic on historical data without re-fetching. Second, document every cleaning decision in a `data_dictionary.md` file — what counts as 'remote', how I bucket seniority levels, etc. Third, flag rather than discard — if a salary is ambiguous, I store it as null with a `salary_quality` flag rather than guessing. That way every downstream analysis can decide for itself how to handle uncertain values."

### "What insights did you find?"

> *Reference your written reports here. Be ready with 2–3 specific findings with numbers.* Example: "One thing that surprised me was that 'SQL + Python + Tableau' as a skill combo carried about a [X]% salary premium over any pair of the three. I expected the premium to be roughly additive — it wasn't."

### "Walk me through your tech stack choices."

> *Use the rationale column from the tech stack table.* Emphasize: Python for ecosystem fit, Metabase because it's what real companies use, raw-then-normalized as the pattern that protects against schema changes.

### "What would you do differently?"

> "Two things. First, I'd start the skill taxonomy earlier — I let it grow organically and ended up with messy categorization that needed a rework in Phase 3. Second, I'd build the data quality dashboard before the analytics dashboard. I had several Phase 3 conclusions I had to revise once I noticed an upstream ingestion bug that had been silently double-counting some postings."

### "How does this scale?"

> "For the current scope — daily ingestion of low-thousands of new postings — Postgres on a single VPS is comfortably over-provisioned. The next scaling step would be partitioning `raw_responses` and `job_snapshots` by date, because those grow monotonically and most queries are time-bounded. Beyond that I'd consider a columnar store like DuckDB or ClickHouse for the analytics layer while keeping Postgres as the operational store."

### "What did you learn?"

> "The biggest lesson was how much of analytics work is judgment under ambiguity. The 'analysis' I imagined I'd be doing — running queries, making charts — was maybe 30% of the time. The other 70% was deciding things like 'what counts as a senior role?' and 'how do I count a job that was reposted under a slightly different title?' Those decisions are invisible in the final dashboard but they determine whether the conclusions are trustworthy. That's the part of analytics I didn't appreciate until I built something end-to-end."

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Adzuna rate limits hit too early | Medium | High | Cache aggressively; pre-compute target searches; supplement with USAJobs |
| Skill extraction has poor precision | High | Medium | Start with regex for top 50 skills (high precision); add spaCy patterns iteratively; manually audit a sample |
| Company name normalization is too lossy | High | Medium | Keep raw names always; build normalization as a *layer*, not a destructive transform |
| Project scope creeps | High | High | Strict phase gates with written acceptance criteria; resist new features until current phase ships |
| Data volume too small for time-series analysis | Medium | Medium | Gate Phase 3 time-series work on having 60+ days of snapshots accumulated |
| I lose interest mid-project | Medium | Very High | Make Phase 5 (writing reports) something I'm genuinely curious about; the project survives if the writing survives |

---

## Success Metrics

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
- **Metabase**: Open-source business intelligence tool; like Tableau but free and self-hosted
- **Normalization (data)**: Cleaning raw values into canonical forms (e.g., 'Meta Platforms Inc' → 'Meta')
- **Prefect**: Python-native workflow orchestration tool; alternative to Airflow with less ceremony
- **Raw-then-normalized**: Pattern of storing API responses verbatim before parsing, enabling schema evolution without re-fetching
- **Snapshot**: A point-in-time record of a job's state, captured daily; enables time-series analysis
- **spaCy**: Production-grade Python NLP library
