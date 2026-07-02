# Phase 1 — Foundation & First Ingestion
## Milestone Plan

> **Phase goal**: Stand up the project's foundation — folder structure, Postgres database, schema v1, a working Adzuna client — and complete the first ingestion of 1,000+ real job postings. End the phase with an initial Jupyter exploration that proves the data is queryable and surfaces the first batch of "what's in this data?" questions.

**Estimated duration**: 2–3 weeks (working evenings/weekends)

---

## Phase 1 Deliverables

By the end of this phase, the following must exist:

- A public GitHub repository with the project structure committed
- A running PostgreSQL database (local Docker for dev) with schema v1 applied via Alembic
- An Adzuna API client that can authenticate and fetch job postings
- An ingestion script that loads 1,000+ jobs into the database idempotently
- One Jupyter notebook (`notebooks/01_initial_exploration.ipynb`) with at least 5 basic visualizations
- A `README.md` with setup instructions sufficient for a stranger to clone and run
- A `data_dictionary.md` skeleton describing every column in every table
- A Phase 1 wrap-up note in `docs/phase_1_findings.md` listing data quality issues discovered

---

## Phase 1 Acceptance Criteria

The phase is **complete** when:

- [ ] Ingestion script runs end-to-end without errors
- [ ] Re-running ingestion produces zero duplicate rows in `jobs`
- [ ] Database contains 1,000+ rows in `jobs` from real Adzuna data
- [ ] Database contains corresponding rows in `raw_responses`, `companies`, and `locations`
- [ ] Alembic migrations apply cleanly to a fresh database
- [ ] Jupyter notebook runs top-to-bottom on a fresh checkout
- [ ] README setup steps have been tested by following them from scratch
- [ ] Code is committed to GitHub with at least 5 meaningful commits

---

## Step-by-Step Build Plan

### Step 1 — Project initialization (Day 1, ~2 hours)

**Goal**: Establish the project structure and version control.

**Actions**:

1. Create a new GitHub repository: `job-market-tracker` (public)
2. Clone locally and `cd` into it
3. Create the folder structure:
   ```
   job-market-tracker/
   ├── src/
   │   ├── ingestion/
   │   ├── cleaning/
   │   ├── models/         # SQLAlchemy models
   │   └── utils/
   ├── notebooks/
   ├── sql/
   │   └── views/
   ├── migrations/         # Alembic
   ├── tests/
   ├── docs/
   ├── docker/
   ├── .env.example
   ├── .gitignore
   ├── README.md
   ├── pyproject.toml
   └── docker-compose.yml
   ```
4. Initialize Python with `uv` or `poetry`:
   ```bash
   uv init                          # or: poetry init
   uv add sqlalchemy alembic psycopg2-binary python-dotenv requests pandas jupyter plotly
   uv add --dev pytest ruff
   ```
5. Create `.gitignore` (Python template + `.env`, `*.sqlite`, `notebooks/.ipynb_checkpoints/`)
6. Create `.env.example` with placeholder keys:
   ```
   ADZUNA_APP_ID=
   ADZUNA_APP_KEY=
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobmarket
   ```
7. First commit: "Initial project structure"

**Acceptance**: `tree -L 2` shows the structure above; `uv run python -c "import sqlalchemy"` succeeds; repo pushed to GitHub.

---

### Step 2 — Local Postgres setup (Day 1, ~1 hour)

**Goal**: Have a running Postgres database for development.

**Actions**:

1. Create `docker-compose.yml`:
   ```yaml
   services:
     db:
       image: postgres:16
       environment:
         POSTGRES_USER: postgres
         POSTGRES_PASSWORD: postgres
         POSTGRES_DB: jobmarket
       ports:
         - "5432:5432"
       volumes:
         - jobmarket_pg_data:/var/lib/postgresql/data
   volumes:
     jobmarket_pg_data:
   ```
2. `docker compose up -d`
3. Verify connection: `psql postgresql://postgres:postgres@localhost:5432/jobmarket -c "select 1;"`
4. Commit: "Add local Postgres via Docker Compose"

**Acceptance**: `docker compose ps` shows the db running; `psql` connects successfully.

---

### Step 3 — Adzuna API registration & smoke test (Day 2, ~1 hour)

**Goal**: Have working API credentials and confirm the API returns data.

**Actions**:

1. Register at https://developer.adzuna.com/
2. Create an app, copy `app_id` and `app_key` into your local `.env` (never commit this)
3. Smoke test in browser or curl:
   ```
   https://api.adzuna.com/v1/api/jobs/us/search/1?app_id=YOUR_ID&app_key=YOUR_KEY&what=data+analyst&results_per_page=10
   ```
4. Inspect the JSON response. Document the shape:
   - Top-level: `count`, `mean`, `results[]`
   - Each `result`: `id`, `title`, `description`, `company.display_name`, `location.area[]`, `salary_min`, `salary_max`, `created`, `redirect_url`, `category.label`, `contract_type`, `contract_time`
5. Save a sample response to `docs/adzuna_sample_response.json` for reference

**Acceptance**: A real API response is saved in `docs/`; documented field list is in your notes.

---

### Step 4 — Schema v1 with Alembic (Day 2–3, ~3 hours)

**Goal**: Database tables exist via reversible migrations.

**Actions**:

1. Initialize Alembic: `alembic init migrations`
2. Configure `alembic.ini` to use the `DATABASE_URL` env var
3. Define SQLAlchemy models in `src/models/`:
   - `raw_response.py` → `RawResponse`
   - `company.py` → `Company`
   - `location.py` → `Location`
   - `job.py` → `Job`
   *(Skills, snapshots, job_skills come later in Phase 2 — keep v1 minimal)*
4. Generate first migration:
   ```bash
   alembic revision --autogenerate -m "initial schema"
   ```
5. Review the generated migration **carefully** — autogenerate is helpful but never trusted blindly
6. Apply: `alembic upgrade head`
7. Verify: `psql ... -c "\dt"` shows the tables
8. Test roll-back: `alembic downgrade base` then `alembic upgrade head` — both should succeed
9. Commit: "Add Alembic with initial schema v1"

**Acceptance**: Migrations apply and reverse cleanly; tables visible in `psql`; SQLAlchemy models match the schema spec in `PROJECT_GUIDE.md`.

---

### Step 5 — Adzuna API client (Day 3–4, ~3 hours)

**Goal**: A Python class that wraps the Adzuna API with rate-limiting and error handling.

**Actions**:

1. Create `src/ingestion/adzuna_client.py`
2. Implement an `AdzunaClient` class with methods:
   - `__init__(app_id, app_key, country='us')`
   - `search(query: str, page: int = 1, results_per_page: int = 50, **filters) -> dict`
   - `iter_search(query: str, max_results: int = 1000)` — generator that paginates
3. Include:
   - Exponential backoff retry on 5xx and rate-limit responses
   - Logging of each request (URL + status + count returned)
   - A `last_request_at` timestamp + minimum delay between calls (be polite)
4. Write a tiny smoke-test script `scripts/smoke_adzuna.py` that prints the first 10 job titles
5. Commit: "Add Adzuna API client"

**Acceptance**: `python scripts/smoke_adzuna.py` prints 10 real job titles from the API.

---

### Step 6 — Ingestion script (Day 4–6, ~6 hours)

**Goal**: A script that fetches jobs and loads them into the database idempotently.

**Actions**:

1. Create `src/ingestion/ingest_adzuna.py`
2. Logic:
   ```
   for each query in target_queries:
       for each page of results:
           1. Save raw response → raw_responses table
           2. For each job in results:
               a. Upsert company by display_name → companies table
               b. Upsert location by (city, state, country) → locations table
               c. Upsert job by external_id → jobs table
                  - INSERT if new
                  - UPDATE last_seen_at if existing
                  - Link to company_id, location_id, raw_response_id
   ```
3. Use SQLAlchemy upserts (`INSERT ... ON CONFLICT DO UPDATE`)
4. Target queries for Phase 1:
   ```python
   QUERIES = [
       "data analyst",
       "senior data analyst",
       "analytics engineer",
       "business intelligence analyst",
       "marketing analyst",
       "product analyst",
   ]
   ```
5. Run ingestion: target ~1,000–2,000 jobs total
6. Run it again immediately to verify idempotency (row counts should not double)
7. Commit: "Add Adzuna ingestion script"

**Acceptance**:
- `select count(*) from jobs;` returns 1,000+
- Running the script twice does not change the count
- Every job row has non-null `company_id`, `location_id`, `raw_response_id`

---

### Step 7 — Initial Jupyter exploration (Day 7–9, ~5 hours)

**Goal**: First analytical pass on the real data. Discover what's there and what's broken.

**Actions**:

1. Launch Jupyter: `jupyter lab`
2. Create `notebooks/01_initial_exploration.ipynb`
3. Connect to the database with pandas + SQLAlchemy
4. Build at least these 5 sections, each with a chart:

   **Section 1 — Volume & freshness**
   - How many jobs total? By source query?
   - Posting date distribution — is the freshness reasonable?

   **Section 2 — Top companies**
   - Top 20 companies by posting count
   - Note: this will reveal the company-name-normalization problem dramatically

   **Section 3 — Salary availability**
   - What fraction of jobs have salary data?
   - When present, distribution of `salary_min` and `salary_max`
   - Salary period — are they all annual? *(spoiler: no)*

   **Section 4 — Geography**
   - Top locations by posting count
   - Remote fraction (using available signals — Phase 2 will refine)

   **Section 5 — Description sniff test**
   - Pull 5 random descriptions, eyeball them
   - Search for occurrences of "Python", "SQL", "Tableau" with simple `LIKE` — get a feel for skill mention rates *(rigorous extraction comes in Phase 2)*

5. End the notebook with a markdown cell titled **"Open questions and data quality issues found"** — list every weirdness you noticed. This becomes the input to Phase 2.

6. Commit: "Add initial exploration notebook"

**Acceptance**: Notebook runs top-to-bottom on a fresh kernel; 5+ charts rendered; observations cell has at least 8 listed items.

---

### Step 8 — Documentation & Phase 1 wrap-up (Day 10, ~3 hours)

**Goal**: Make the project explainable and the phase formally closed.

**Actions**:

1. Write `README.md`:
   - Project description (use elevator pitch from `PROJECT_GUIDE.md`)
   - Tech stack
   - Setup instructions (Docker, env vars, migrations, running ingestion)
   - Project status: "Phase 1 complete — see `docs/` for details"
2. Write `docs/data_dictionary.md` v1:
   - Every table, every column, what it means, what populates it
3. Write `docs/phase_1_findings.md`:
   - What worked
   - Data quality issues found (from the notebook's observations cell)
   - Surprises
   - What this means for Phase 2 priorities
4. Final commit: "Phase 1 complete"
5. Tag the release: `git tag phase-1 && git push --tags`

**Acceptance**: Following the README from a fresh clone results in a working setup; data dictionary covers every column; findings doc is thoughtful and specific.

---

## Common Pitfalls to Watch For

**1. Storing API keys in code.** Use `.env` + `python-dotenv` from day one. Never commit `.env`. Verify with `git status` before every push.

**2. Skipping `raw_responses`.** It is tempting to parse and discard the raw JSON. Don't. When Phase 2 reveals a parsing bug, you'll want the raw data to re-process. This is the single most important architectural rule.

**3. Premature normalization.** In Phase 1, store company names *as-is* from the API. Don't try to deduplicate "Meta" and "Facebook" yet — that's Phase 2 work, and doing it incrementally is a trap. Just upsert by exact string match for now and let Phase 1 reveal how bad the problem is.

**4. Over-engineering the ingestion script.** Phase 1 does not need Prefect, retries-with-jitter, or perfect error handling. A working linear script is the goal. Polish in Phase 6.

**5. Ingesting too aggressively.** Adzuna's free tier is 1,000 calls/month. With 50 results per page, that's 50,000 job rows of capacity per month — plenty, but easy to burn through if you re-run the script while testing. Use a `--dry-run` flag or a small page limit during development.

**6. Letting the notebook become a kitchen sink.** Keep `01_initial_exploration.ipynb` short and focused. Future deeper investigations belong in numbered follow-up notebooks (`02_company_normalization_exploration.ipynb`, etc.).

**7. Not testing migrations both directions.** Always `alembic downgrade` and re-`upgrade` after writing a migration. Catching reversibility bugs in Phase 1 is cheap; catching them in Phase 5 is expensive.

---

## Tools Reference (Phase 1)

| Tool | First-time install / setup |
|---|---|
| Docker Desktop | https://www.docker.com/products/docker-desktop |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Adzuna account | https://developer.adzuna.com/signup |
| psql client | `brew install libpq` (Mac) or system package manager |
| DBeaver (optional GUI) | https://dbeaver.io/ |

---

## End-of-Phase Checklist

Before declaring Phase 1 complete, verify all of the following:

- [ ] `git clone` + follow README → working local setup
- [ ] `docker compose up -d` brings up Postgres
- [ ] `alembic upgrade head` creates all schema v1 tables
- [ ] `python -m src.ingestion.ingest_adzuna` runs without error
- [ ] After ingestion, `select count(*) from jobs;` ≥ 1000
- [ ] Re-running ingestion does not increase the count
- [ ] `jupyter lab` opens `01_initial_exploration.ipynb` and it runs top-to-bottom
- [ ] README, data dictionary, and findings doc all exist and are complete
- [ ] `phase-1` git tag pushed to GitHub
- [ ] Spent 10 minutes mentally rehearsing how to explain Phase 1 in an interview

---

## Transition to Phase 2

Phase 2 takes the messy Phase 1 dataset and turns it into something analyzable. The `phase_1_findings.md` document is the input to Phase 2 planning — every data quality issue listed there becomes a Phase 2 task. Common items expected to appear:

- Company name duplication
- Salary period inconsistencies (annual vs hourly)
- Location string variation
- Title variation requiring normalization
- Skill mentions buried in unstructured descriptions

Do not start Phase 2 until Phase 1's acceptance criteria are all checked. Discipline on phase gates is the difference between a finished project and a perpetually-in-progress one.
