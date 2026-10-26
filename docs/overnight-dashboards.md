# Overnight run: Metabase dashboards as code (Milestone C)

## Report

- **Branch:** `claude/metabase-dashboards`, off `main` at `8c20506` ("Merge pull request #2 from PloypairaohPat/claude/daily-clock"). This session's setup named a different working branch; per the brief, everything went to `claude/metabase-dashboards`.
- **Commits on top of main `8c20506`:** 8, plus this report (listed below). **Pushed:** yes, after every commit. No force push, nothing to `main`, no PR.
- **STOP conditions:** none held.
  - `8c20506` is in main's history.
  - `src/cleaning/data/skills.json` and `company_aliases.json` both exist.
  - The baseline was green.
  - `alembic heads` showed one head (`a02471448340`).
  - main had no `dashboards/`, no `src/dashboard/`, and no metabase service.
  - The Metabase image pulled on attempt 2 of 3 (see Surprises).
- **Verification:** run on local Postgres 16, with a fresh `jobmarket_test` before every commit. Versions: Python 3.13, SQLAlchemy 2.1.6, alembic 1.20.1, psycopg2-binary 2.9.13, pytest 9.1.1, ruff 0.17.2.

| Check | Baseline (clean main) | Final |
|---|---|---|
| `pytest` with `TEST_DATABASE_URL` | 363 passed, 0 failed, 0 skipped | **447 passed, 0 failed, 1 skipped**. The skip is the Metabase e2e test, which needs `METABASE_URL` |
| `ruff check .` (0.17.2) | clean | clean |
| `ruff format --check .` (0.17.2) | clean, 90 files | clean, 103 files. One commit was pushed red; see Surprises |
| alembic upgrade → downgrade → upgrade on a fresh database | clean | clean (no migration in this milestone) |
| `make views` on a fresh alembic-built database, twice | 7 views | **9 views**, twice |
| Metabase version pinned | — | **`metabase/metabase:v0.64.3.4`** (build 2026-10-23, `3d6c89f`), read from `/api/session/properties` |
| E2E (`tests/test_metabase_e2e.py`) on the compose `metabase` service, fresh instance, reading `jobmarket_demo` loaded with `--full` | — | **passed**. First run did the setup; the second run was identical (same ids, created/updated/deleted all empty); 28 cards in the collection, no duplicates; all 28 cards ran with status `completed`, no errors, rows returned |
| Rendering check (Playwright, screenshots in the scratchpad only) | — | **6/6 pass**: every dashcard rendered, no loading or error state, demo banner present (per-dashboard table below) |
| `docker compose config`, with and without `--profile bi` | — | both valid. Plain `docker compose --dry-run up -d` starts only `db`; `--profile bi` adds `metabase` |
| GitHub Actions CI on the branch | — | runs #7–#11 and #13 **green**; **#12 (`4c20b87`) red** on `ruff format --check`, fixed by #13 (`b2c98b7`); #14 (`72bf910`) still running when this was written |

Rendering check per dashboard (cards = all dashcards on the page, including the demo banner):

| Dashboard | Cards (questions / text incl. banner) | Result |
|---|---|---|
| Ingestion health | 10 (7 / 3) | pass |
| Market overview | 7 (5 / 2) | pass |
| Salary | 6 (4 / 2) | pass |
| Skills | 6 (4 / 2) | pass |
| Transparency | 6 (4 / 2) | pass |
| Visa outlook | 7 (4 / 3) | pass |

The first rendering pass also passed the automated checks, but looking at the screenshots showed real problems:
- **Intro text cut off mid-caveat:** Salary's "never blended" sentence was clipped.
- **Data-window tables clipped their n columns.**
- **The daily line chart drew straight across the missing day.**

All three are fixed in `4c20b87`, re-provisioned through the update path (14 items updated in place, then a further run made 0 changes), and re-rendered.

- **Compare:** https://github.com/PloypairaohPat/job-market-tracker/compare/main...claude/metabase-dashboards?expand=1
- **No live job or government API was called.**
  - No Adzuna or USAJobs credentials exist in this environment.
  - Every ingestion here ran through fixture-backed clients:
    - `FixtureClient`, `FakeEmployerClient` and `FixtureUSAJobsClient` in `src/dashboard/demo_dataset.py`, whose `iter_search` serves local JSON;
    - the existing test fixtures.
  - I never ran an ingest `main()`, the daily runner or `smoke_adzuna.py`.
  - The only outbound traffic was the Docker image pull (`registry-1.docker.io`, then `mirror.gcr.io`), plus GitHub (push and CI status).
- **VM-only changes, not in the repo** (needed so the Metabase container can reach the VM's Postgres):
  - `/etc/postgresql/16/main/postgresql.conf`: added `listen_addresses = 'localhost,172.17.0.1'`.
  - `pg_hba.conf`: added `host all all 172.17.0.0/16 scram-sha-256` (Docker bridge) and `host all all 172.18.0.0/16 scram-sha-256` (the compose project network).
  - Postgres restarted, then reloaded.
  - `dockerd` started by hand, because `service docker start` failed on `ulimit` in this sandbox.
  - A scratchpad-only compose override added `extra_hosts: host.docker.internal:host-gateway`, which Docker Desktop provides on its own.

## What shipped

| # | Commit | What |
|---|---|---|
| 0 | `c5ed00f` | `metabase_reader` role: SELECT on `v_*` views only (`make bi-grant`) |
| 1 | `7da201b` | `seed_demo_data.py --full`: deterministic, idempotent full demo dataset |
| 2 | `2887b29` | Two dashboard views: `v_ingestion_runs`, `v_market_jobs` |
| 3 | `f782047` | `dashboards/` (6 JSON specs, 28 SQL files) + `src/dashboard/spec.py` validator + tests |
| 4 | `4ed6b53` | Metabase compose service (profile `bi`, pinned v0.64.3.4) + `src/dashboard/provision.py` + tests |
| 5 | `4c20b87` | Layout fixes found by the rendering check (**pushed with a ruff-format failure**) |
| 5b | `b2c98b7` | Formatting fix for 5 |
| 6 | `72bf910` | Docs: `docs/dashboard.md`, data dictionary, README |
| 7 | *(this commit)* | This report |

**0. Reader role.**
- `python -m src.dashboard.reader_role` connects with the owner's `DATABASE_URL` and creates or updates a LOGIN role with these attributes: `nosuperuser nocreatedb nocreaterole noinherit`.
- It grants CONNECT and USAGE on `public`, revokes every table and sequence privilege, then grants SELECT on each `v_*` view from `pg_views`.
- The password comes from `METABASE_READER_PASSWORD` and is never printed. Role names are validated as plain identifiers before going into DDL.
- Tests run as the role:
  - every view is readable;
  - `jobs`, `lca_cases`, `raw_responses`, `ingestion_runs` and `companies` give permission denied;
  - re-granting is idempotent and picks up new views, but not non-`v_` ones;
  - a stray table grant is revoked.
- The test role is dropped afterwards.

**1. Full demo dataset.** See the data dictionary for everything it contains.
- `--full` truncates its target, so it refuses anything but localhost/127.0.0.1 with "demo" or "test" in the database name.
- The default mode is unchanged (600 jobs, 15 companies, 9 locations). I didn't add the guard there, because the README's quick start seeds the main `jobmarket` database (Q5).
- Determinism:
  - a fixed seed;
  - a fixed time of day for every timestamp (`raw_responses.fetched_at`, `companies.created_at`, `lca_cases.loaded_at`, `job_visa_signals.classified_at`);
  - `TRUNCATE ... RESTART IDENTITY`.
- The test checks an md5 fingerprint of every table and gets identical results after a re-run.
- On `jobmarket_demo`:
  - 614 jobs in the analysis population (609 commercial, 5 federal);
  - 27 snapshot days with one gap;
  - 54 run rows (52 ok, 1 failed, 1 skipped_budget);
  - buckets: closed 6, strong 4, possible 1, unknown 603.

**2. Views.**
- `v_ingestion_runs` is the run log without `params` or `error`, for a public dashboard.
- `v_market_jobs` holds one row per job in the analysis population, with `metro_area` and `seniority` labelled instrument-limited.
- Salary-by-seniority aggregates `v_commercial_salary_clean` in card SQL, so it needed no view.
- No existing view changed.

**3. Dashboards as files.**
- Six JSON specs and 28 SQL files. Every dashboard opens with a sources/mirrors text card and a data-window card.
- `spec.py` parses FROM/JOIN targets, including comma lists, schema-qualified and quoted names, CTEs (which shadow), subqueries, and set-returning functions. It ignores comments, strings and `extract(... from ...)`.
- It then enforces all eight rules from the brief, with one test per rule.
- The 24-column grid comes from v0.64.3.4's own frontend bundle (`{desktop:24,mobile:1}`), not from memory.
- An integration test runs every card as a fresh reader role on the full demo data: at least one row each, and an `n`/`n_*` column on every aggregate. CI runs it.

**4. Metabase service and provisioner.**
- The compose service: `profiles: ["bi"]`, `127.0.0.1:${METABASE_PORT:-3000}:3000`, H2 on the `metabase_app_data` volume, `MB_ANON_TRACKING_ENABLED=false`, a curl healthcheck, and `depends_on: db (healthy)`.
- The provisioner is written against v0.64.3.4's `/api/docs/openapi.json` and checked on the live instance:
  - cards carry **MBQL 5** native queries (`{"lib/type":"mbql/query","stages":[{"lib/type":"mbql.stage/native",...}]}`);
  - dashcards are saved with `PUT /api/dashboard/{id}` and negative ids for new ones.
- Items are matched by a "Defined in dashboards/…" line at the end of each description (Q6).
- It only prunes marked items inside the collection, adds the demo banner on demo/test databases, and creates public links only with `--public-links` and only for `public: true`. A private dashboard never keeps a link.
- `--reconnect` re-sends the connection details after a password rotation.
- Secrets are masked in values, errors and logs, and network errors exit 1.
- Eleven unit tests run against an in-memory fake Metabase:
  - first-run setup;
  - idempotent second run;
  - in-place update;
  - pruning confined to the collection, including duplicates;
  - `--dry-run` making no write call (on fresh and on built instances);
  - public links;
  - no password or session token in logs or errors;
  - missing settings named;
  - a network error exiting 1;
  - config defaults.

**5. Rendering.** See the table above. The layout commit is in the repo; the screenshots stay in the scratchpad.

**6. Docs.**
- `docs/dashboard.md` is written for the owner.
- The data dictionary gains: `metabase_reader`, both views, the card rules, and the demo dataset and its limits.
- README: a Dashboard section, project structure and the docs index.
- Makefile: `bi-grant`, `bi-up` and `bi-provision`, with `##` help.

## Dashboards

**Ingestion health** (public):
- Data window → `v_ingestion_daily`
- Distinct jobs observed per day, by source → `v_ingestion_daily`
- New jobs per day, by source → `v_ingestion_daily`
- Adzuna API calls per day → `v_ingestion_daily`
- Runs by source and status → `v_ingestion_runs`
- Current streak vs 60-day target → `v_ingestion_daily`
- Missing days → `v_ingestion_daily`
- Text: intro; "Reading gaps"

Caveats:
- A missing day is a gap (the line breaks), never a zero, and is never backfilled.
- Dates are UTC.
- Days before the run log show 0 runs and blank calls.
- It mirrors `python -m src.pipeline.health`.

**Market overview** (public):
- Data window → `v_market_jobs` + `v_ingestion_daily`
- Jobs by market → `v_market_jobs`
- Jobs by tracked metro (allowlist; instrument-limited) → `v_market_jobs`
- Seniority mix by market (title-only; instrument-limited) → `v_market_jobs`
- Top employers by normalized name → `v_market_jobs`
- Text: intro

Caveats:
- Metro is the tracked-metro allowlist, not all locations.
- "No title signal" is shown and never folded into mid.
- Postings with no company are counted separately.
- Compare the markets' shapes, not their totals.

**Salary** (public):
- Data window (n disclosed and n predicted kept separate) → `v_commercial_salary_clean`
- Disclosed salary distribution → `v_commercial_salary_clean`
- Disclosed median by seniority, with n → `v_commercial_salary_clean`
- Comparison: Adzuna-predicted vs employer-disclosed → `v_commercial_salary_clean`
- Text: intro

Caveats:
- Headline numbers are employer-disclosed only.
- Predicted salaries appear only in the comparison, split by `salary_is_predicted`, never blended.
- Commercial, annual USD, `'ok'` quality only.
- p25/p75 sit beside each median, with a `small_n` flag.

**Skills** (public):
- Data window → `v_skill_category_composition`
- Skill-tag share by category, per market → `v_skill_category_composition`
- Top commercial skills → `v_skill_top_by_source`
- Top federal skills → `v_skill_top_by_source`
- Text: intro

Caveats:
- Commercial text is truncated at about 500 characters, so a skill's absence isn't evidence it isn't required. This is on every skills card.
- It shows composition, not magnitude.
- Each rate sits beside its n; the write-up's n thresholds are 15 commercial and 5 federal.

**Transparency** (public):
- Data window → `v_field_completeness`
- Salary: present vs employer-disclosed → `v_field_completeness`
- Fields that are market facts → `v_field_completeness`
- Instrument-limited fields (not market facts) → `v_field_completeness`
- Text: intro

Caveats:
- `pct_seniority_present` (title-only), `pct_metro_present` (allowlist) and federal `pct_remote_true` (`description_full` not read) are labelled instrument-limited.
- Skills completeness is capped by truncation.

**Visa outlook** (`public: false`):
- Data window → `v_job_visa_outlook`
- Jobs per bucket → `v_job_visa_outlook`
- Strong and possible jobs (company, metro, `bucket_reason`, LCA counts, `redirect_url`) → `v_job_visa_outlook`
- Employer sponsorship history (last 3 FYs) → `v_employer_sponsorship`
- Text: intro; "What this can't tell you"

Caveats (all of `src/visa/README.md`'s list):
- An LCA is not an approval or a hire.
- Counts favour large filers.
- Truncated text hides signals (unknown is not "no").
- Cap-exempt is only a hint.
- E-Verify isn't covered.
- Rules change, so check with your DSO.

## Parked questions

| Q | Question | Recommendation (built) |
|---|---|---|
| 1 | Metabase app database: H2 or Postgres | (a) H2 on a volume for the laptop; Postgres on Hetzner |
| 2 | Public links: when, and which dashboards | (a) after Hetzner; all but Visa outlook |
| 3 | Small-n threshold | (a) n everywhere + `small_n` flag below 10 |
| 4 | Visa outlook in Metabase? | (a) keep it, private |
| 5 | Guard the default (non-`--full`) seed mode? | (a) no guard (it would break the README quick start) |
| 6 | Matching across renames; what pruning may delete | (a) key via a description line; prune only marked items in the collection |
| 7 | Bumping the pinned Metabase version | (a) bump the tag, dry-run, provision, e2e test |
| 8 | Bump actions/checkout and setup-python (Node 20) | (a) bump when the CI warning becomes an error |
| 9 | Rotating the reader password | (a) explicit `--reconnect` |
| 10 | Scope of the instrument-limited label rule | (a) strict: any card touching those five fields |

### Q1. Metabase app database
- **What I found:** Metabase stores users, cards and dashboards in its app database. Here every card and dashboard is rebuilt from `dashboards/`, so the laptop's app database holds nothing that can't be recreated except the admin login.
- **Options:**
  - (a) H2 on the `metabase_app_data` volume.
  - (b) Postgres: a separate `metabase_app` database in the same `db` service.
  - (c) H2 on the laptop and Postgres on Hetzner.
- **Recommendation:** (a) built for the laptop, then (c). Metabase itself advises against H2 for production, and Hetzner is where public viewers arrive.

### Q2. Public links
- **What I found:** the provisioner can enable public sharing and link dashboards marked `public: true`. Metabase binds to 127.0.0.1, so a link from the laptop would only work on the laptop anyway.
- **Options:**
  - (a) Turn links on after the Hetzner deploy (HTTPS, reverse proxy), for all but Visa outlook.
  - (b) Turn them on now via a tunnel.
  - (c) Never; take screenshots for the portfolio instead.
- **Recommendation:** (a). Run `--public-links` on Hetzner. Visa outlook is `public: false`, and the provisioner removes any link it finds on it.

### Q3. Small-n threshold
- **What I found:** the Phase 3 write-ups used n ≥ 15 (commercial) and n ≥ 5 (federal) when drawing tables. Dashboards are browsed, not read in order, so hiding groups would quietly change totals.
- **Options:**
  - (a) Show n everywhere, plus a `small_n` flag below 10.
  - (b) Hide groups below a threshold.
  - (c) Per-market thresholds (15/5) in the card SQL.
- **Recommendation:** (a), built on the metro and salary-by-seniority cards. The skills tables show `n_jobs_tagged` and `market_n_jobs` beside each rate.

### Q4. Visa outlook dashboard
- **What I found:** it's the owner's job-search view, and it carries LCA aggregates that only make sense with the caveats.
- **Options:**
  - (a) Keep it in Metabase, `public: false`.
  - (b) Drop it from Metabase and keep only `python -m src.visa.scan`.
  - (c) Move it to a separate private collection.
- **Recommendation:** (a). It's never linked publicly, but anyone with a Metabase login on the laptop can see it. If Hetzner gets more users, consider (c) with collection permissions.

### Q5. Guarding the default seed mode
- **What I found:** the README's quick start runs `seed_demo_data.py` against `DATABASE_URL=…/jobmarket`, the real database name. A demo/test guard there would break that documented use. The default mode only upserts (it never truncates), so it's far less dangerous than `--full`.
- **Options:**
  - (a) Leave it unguarded.
  - (b) Guard it and change the README to seed a `jobmarket_demo` database.
  - (c) Print a warning when the name isn't demo/test.
- **Recommendation:** (a), built. (c) is a cheap middle ground if you want one.

### Q6. Matching across renames, and what pruning may delete
- **What I found:** Metabase has no free-form metadata field. `POST /api/card` accepts an `entity_id`, but `POST`/`PUT /api/dashboard` don't.
- **Options:**
  - (a) A "Defined in dashboards/sql/<key>.sql" (or `dashboards/<slug>.json`) line at the end of each description, matched by key.
  - (b) Deterministic `entity_id`s for cards plus name matching for dashboards.
  - (c) Match by name.
- **Recommendation:** (a), built. The line is useful to viewers (where to edit) and survives title renames. Renaming a **key** creates a new item and deletes the old one.
- **What pruning touches:** only items inside the *Job Market Tracker* collection that carry the line. Hand-made items and other collections are never touched, and edits to provisioned items are overwritten.

### Q7. Metabase version upgrades
- **What I found:** the request shapes changed recently (MBQL 5 native queries), and the grid width is a frontend constant.
- **Options:**
  - (a) Pin an exact tag. To upgrade, bump it, run `provision --dry-run`, then provision, then the e2e test, which runs every card.
  - (b) Track `latest`.
  - (c) Pin by digest.
- **Recommendation:** (a), built and documented in `docs/dashboard.md`. Re-check `GRID_COLUMNS` in `spec.py` when bumping.

### Q8. Node 20 warning in CI
- **What I found:** GitHub warns that `actions/checkout@v4` and `actions/setup-python@v5` target Node 20 and are forced onto Node 24. CI passes. This is out of scope tonight.
- **Options:**
  - (a) Bump both to their next majors once released and verified.
  - (b) Pin by commit SHA.
  - (c) Ignore it until it breaks.
- **Recommendation:** (a), as a one-line change in its own small PR.

### Q9. Rotating the reader password
- **What I found:** Metabase returns the stored password masked, so the provisioner can't tell whether it changed. Re-sending it on every run would break "a second run changes nothing".
- **Options:**
  - (a) An explicit `--reconnect` flag.
  - (b) Always re-send.
  - (c) Edit the connection in the Metabase UI.
- **Recommendation:** (a), built and documented.

### Q10. Scope of the instrument-limited label rule
- **What I found:** the brief names the three `v_field_completeness` columns. `v_market_jobs` exposes `metro_area` and `seniority`, which carry the same caveat.
- **Options:**
  - (a) Strict: any card whose SQL touches `pct_seniority_present`, `pct_metro_present`, `pct_remote_true`, `metro_area` or `seniority` must say "instrument-limited".
  - (b) Only the three completeness columns.
- **Recommendation:** (a), built. It covers the salary-by-seniority and visa-jobs cards, whose descriptions say so.

## What the owner must do locally

Nothing here can touch your laptop. In **Windows PowerShell**, from the repo root, after merging the PR:

```powershell
# 1. code + dependencies
git checkout main
git pull
uv sync

# 2. schema and views (Postgres up: docker compose up -d)
uv run alembic upgrade head
uv run python scripts/apply_views.py          # -> "9 views applied"

# 3. three new variables in .env -- with Notepad, NEVER echo / >>
notepad .env
#   METABASE_ADMIN_EMAIL=you@example.com
#   METABASE_ADMIN_PASSWORD=<long password for the Metabase admin>
#   METABASE_READER_PASSWORD=<different long password for the read-only role>

# 4. read-only role (re-run whenever a view is added)
uv run python -m src.dashboard.reader_role

# 5. start Metabase (opt-in profile; the daily task is unaffected)
docker compose --profile bi up -d
#    first start takes 1-2 minutes; wait until this prints {"status":"ok"}:
curl.exe -s http://localhost:3000/api/health

# 6. build every dashboard (first run also creates the admin user)
uv run python -m src.dashboard.provision --dry-run
uv run python -m src.dashboard.provision
uv run python -m src.dashboard.provision      # second run: "created 0, updated 0, deleted 0"
```

Then open **http://localhost:3000**, log in with the admin email and password, and open the **Job Market Tracker** collection. There's no demo banner, because your database is `jobmarket`.

**Look first at Ingestion health**, since it tells you whether the others can be trusted:
- The data window should match `uv run python -m src.pipeline.health`: the same first snapshot date, the same snapshot days and the same streak.
- Missing days should be the days you know the laptop was off.

**Cross-check against the views and report #1** (`docs/phase_3_findings.md`):
- **Salary:**
  - n disclosed vs n predicted in the data window should match `select salary_is_predicted, count(*) from v_commercial_salary_clean group by 1`.
  - Report #1 had 178 disclosed and 1,303 predicted, with a disclosed median of **$98,500** and a predicted median of $104,197. Expect today's numbers to have moved with more data, but in the same direction.
  - In the disclosed-by-seniority card, senior should be the only band with a large n (report #1: senior 57, no title signal 110).
- **Transparency:**
  - commercial `pct_salary_disclosed` (report #3: 12.1%);
  - federal `pct_salary_disclosed` 100%;
  - commercial `pct_metro_present` (8.9%).
- **Market overview:** the jobs-by-market totals should equal `n_jobs` in `v_field_completeness`.
- **Visa outlook:** until you load LCA files it will be almost all `unknown`, with closed/strong only from posting text. That's expected.

To stop Metabase without stopping Postgres or the daily task:

```powershell
docker compose --profile bi stop metabase
```

## Surprises

- **Docker Hub rate limit.** The first pull got `429 Too Many Requests` from `registry-1.docker.io`, because anonymous pulls are rate-limited per egress IP and this sandbox shares one. Attempt 2 pulled the same image through `mirror.gcr.io` (Google's public Docker Hub cache). Its digest, `sha256:7804ce4e…`, is the one the `v0.64.3.4` tag resolves to. I tagged it locally as `metabase/metabase:v0.64.3.4`, which is the name compose uses. On your machine compose pulls from Docker Hub normally.
- **The API differs from older docs.** In v0.64 a card's `dataset_query` is MBQL 5 (`stages` with a `mbql.stage/native` stage). The older `{"type":"native","native":{"query":…}}` is still accepted but converted. The provisioner writes the new shape.
- **I pushed one red commit.** `4c20b87` (the layout fixes) went out with `ruff format --check` failing on one line I had lengthened with `sed`. My verify script printed the failure but didn't exit non-zero, so the chained commit and push went ahead. `b2c98b7` fixed it (CI #13 green), and I switched to a gate script that exits 1 on any red check before every later commit. History wasn't rewritten.
- **Passing automated checks weren't enough.** The first Playwright pass reported 6/6 OK while the Salary intro was cut off mid-caveat and the line chart bridged the missing day. Only looking at the screenshots caught it. The selector-based check verifies loading and error states, not layout.
- **Unexpected compose network.** The compose project network is 172.18.0.0/16, not the default bridge's 172.17.0.0/16, so Postgres needed a second `pg_hba` line here. On Docker Desktop the container reaches `db` by name on the compose network, so this doesn't apply to you.
- **The demo's federal market is tiny.** It's 5 in-scope postings. Top federal skills show n = 1–2 per skill; the n is always visible.

## Suggested PR title

**Metabase dashboards as code: read-only role, demo dataset, 6 dashboards, provisioner**

<details>
<summary>PR description (ready to paste)</summary>

## Summary

Milestone C: Metabase dashboards that read the same SQL views as the written reports and carry the same caveats, defined as files and built by one idempotent command.

- **Read-only role:** `python -m src.dashboard.reader_role` (`make bi-grant`) creates `metabase_reader`, which can SELECT every `v_*` view and no base table, so dashboards can't bypass the views.
- **Demo dataset:** `seed_demo_data.py --full` builds a deterministic, idempotent synthetic dataset where every panel has data:
  - both markets;
  - 28 days of history with one gap;
  - a run log with a failed and a budget-skipped run;
  - every visa bucket, with sponsorship/LCA data only at FAKE employers.

  It only runs against a local demo/test database.
- **Two views:** `v_ingestion_runs` (the run log minus `error`/`params`) and `v_market_jobs` (the analysis population by market, with metro and seniority labelled instrument-limited).
- **Dashboards as files:** `dashboards/*.json` (6 dashboards) and `dashboards/sql/*.sql` (28 cards). `src/dashboard/spec.py` validates them:
  - `v_*` views only;
  - every card described;
  - predicted and disclosed salary never blended;
  - the skills truncation caveat;
  - instrument-limited labels;
  - Metabase's 24-column grid;
  - SQL files exist and keys are unique.

  Every card runs as the reader role on the demo data in CI.
- **Metabase service:** pinned `metabase/metabase:v0.64.3.4` in an opt-in `bi` compose profile, bound to 127.0.0.1, with an H2 app database. `python -m src.dashboard.provision` (`make bi-provision`):
  - runs first-time setup;
  - connects as the reader role;
  - creates or updates every card and dashboard in a "Job Market Tracker" collection, matched by key;
  - prunes only its own items;
  - adds a DEMO DATA banner on demo databases;
  - creates public links only with `--public-links`.

  A second run changes nothing.
- **Docs:** `docs/dashboard.md`, the data dictionary and the README.

## Testing

- `pytest` with `TEST_DATABASE_URL`: 363 → **447 passed**, 1 skipped (the Metabase e2e test, which needs `METABASE_URL`).
- `ruff check .` and `ruff format --check .` (0.17.2) are clean, the alembic round trip is clean, and `make views` applies 9 views, twice.
- E2E against a real Metabase v0.64.3.4 container on the demo data:
  - provisioned twice with the same ids and no duplicates;
  - all 28 cards return rows with no errors.
- Playwright rendering check: all 6 dashboards render with no error states.
- No live job or government API was called: all ingestion used fixture-backed clients.

## Open questions

10 parked decisions are in `docs/overnight-dashboards.md`, each with the default that was built:
- the app database (H2 vs Postgres)
- when to turn on public links
- the small-n flag
- the private visa dashboard
- the default seed guard
- key matching and pruning
- version upgrades
- the Node 20 CI warning
- rotating the reader password
- the instrument-limited rule's scope

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01ATh4ABgiML8G58MzgJ36ZP

</details>
