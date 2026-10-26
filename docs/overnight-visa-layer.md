# Overnight run: visa-sponsorship layer

## Report

- **Branch:** `claude/visa-sponsorship-layer`, off `main` at `34ad172` ("Phase 3 #3: field completeness / transparency profile")
- **Commits on top of main `34ad172`:** 7 commits plus this report (listed below). **Pushed:** yes.
- **STOP conditions:** none held. `34ad172` is in main's history, both `src/cleaning/data/skills.json` and `company_aliases.json` exist, the baseline was green, and `alembic heads` showed one head (`54cb52b13dc1`, now `6f399ab4542e`).
- **Verification** (local Postgres 16, `jobmarket_test` on 127.0.0.1, dropped and recreated before every run; SQLAlchemy 2.1.6, alembic 1.20.1, psycopg2-binary 2.9.13, ruff 0.17.2, Python 3.13):

| Check | Baseline (clean main) | Final |
|---|---|---|
| `pytest` with `TEST_DATABASE_URL` | 182 passed, 0 failed, 0 skipped | **310 passed, 0 failed, 0 skipped** |
| `ruff check .` | clean | clean |
| `ruff format --check` on changed .py files | n/a | 21 files already formatted (the four files on main that already fail weren't touched) |
| `alembic upgrade head && downgrade base && upgrade head` | clean | clean |
| `make views` twice on a fresh alembic-built DB | n/a (4 views, applied by hand) | 6 views applied, twice |
| NUL bytes in README.md | present (from byte 6319) | none |
| `git diff main --stat` data files | n/a | none (no .xlsx, .csv or `data/`) |

- **Compare:** https://github.com/PloypairaohPat/job-market-tracker/compare/main...claude/visa-sponsorship-layer?expand=1

## What shipped

| # | Commit | What |
|---|---|---|
| 0 | `c096d4f` | Safety and setup: conftest guard, psycopg2 URLs, README NUL fix, `scripts/apply_views.py` + `make views` |
| 1 | `6b40a0a` | `lca_cases` model + migration; allowlisted .xlsx/.csv LCA loader CLI |
| 2 | `578be17` | `v_employer_sponsorship` view; cross-set company ↔ LCA match-candidate finder |
| 3 | `b3a40d5` | Posting-text classifier; `job_visa_signals` table + migration; `visa` step in apply_cleaning |
| 4 | `08618d6` | `v_job_visa_outlook` view; `python -m src.visa.scan` |
| 4b | `13cc151` | `lca_loader --rekey`: recompute `employer_key` after alias edits without reloading files |
| 5 | `565732d` | Docs: data dictionary, `src/visa/README.md` (incl. "What this can't tell you"), README structure |
| 6 | *(this commit)* | This report |

**0. Safety and setup.**
- `tests/conftest.py::reset_schema` now calls `assert_safe_test_url`. It refuses unless the host is `localhost` or `127.0.0.1` and the database name contains `test`, and it does this before any connection is made. Tested in `tests/test_conftest_guard.py`, including "name lacks test", remote hosts, a unix socket, and a refusal before connecting.
- `.env.example` and the README test command now use `postgresql+psycopg2://`.
- README.md is cut at byte 6318, just before the UTF-16 `# job-market-tracker`. It now ends with "API response shape reference\n" and contains no NUL bytes.
- `scripts/apply_views.py` applies `sql/views/*.sql` in file-name order, in one transaction, against `DATABASE_URL`, through SQLAlchemy. It uses a raw DBAPI cursor with no parameters, because the existing views' comments contain `%`, which psycopg2 otherwise tries to interpolate (first attempt failed on exactly that). It has a `make views` target and is documented in the README. Integration tests call `apply_views()` after `reset_schema`.

**1. LCA loader.**
- `lca_cases` holds the 30 allowlisted columns in snake_case, plus `fiscal_year`, `source_file`, `loaded_at` and `employer_key`. The primary key is `case_number`, and `employer_key` and `fiscal_year` are indexed.
- `src/visa/lca_loader.py` streams .xlsx files (openpyxl, read-only) and .csv files row by row. It keeps only the allowlisted header positions, so personal-data cells are dropped as each row is read and never sit in a DataFrame.
- It upserts in batches on `case_number`, with the latest load winning, and duplicates within a file keep the last occurrence. Defensive parsers turn bad flags, dates, ints and wages into NULL and count them per column. A file missing CASE_NUMBER, CASE_STATUS or EMPLOYER_NAME is refused. It prints counts by `case_status` and `visa_class`, and `--dry-run` writes nothing.
- openpyxl is the only new dependency.
- Tests use synthetic .xlsx and .csv files built inside the test, with invented POC, attorney, lawfirm and preparer values. They check that no such column or value reaches the DB, that a cumulative Q2 → Q3 reload converges to three cases, and that bad cells are counted while the load still succeeds.

**2. Employer sponsorship view and match review.**
- `v_employer_sponsorship` has one row per employer and FY, plus a `last_3_fy` row. Columns:
  - certified H-1B count, with its new-employment and analytics-SOC subsets (and both together)
  - wage-level mix I–IV and NA
  - median offered annual wage, with unconvertible units counted
  - latest certified decision date
  - any H-1B-dependent or willful-violator filing
- The SOC list is a documented `VALUES` CTE in the view, the one place to edit it.
- `src/visa/sponsor_match.py` uses first-token blocking and the same containment and fuzzy rule as `find_merge_candidates`. That rule was pulled into `company_normalizer.classify_pair()` with no behaviour change, and the existing tests are unchanged and green.
- The finder writes `data/sponsor_match_candidates.csv` with an empty `approved` column and never merges anything itself. Its test checks that `company_aliases.json` is byte-identical afterwards.

**3. Posting-text signals.**
- `src/visa/posting_signals.py` is pure and table-driven, with a reason string on every output (rules in the data dictionary).
- The `visa` step rebuilds `job_visa_signals` for all jobs. For USAJobs it reads `KeyRequirements` from the job's raw page, matching `MatchedObjectId` to `external_id`.
- Across 84 test cases (mostly parametrised), the tests cover every case listed in the brief plus traps: EEO "citizenship status", "executive sponsor", "opt in", "CPT codes", "help us persuade", "no security clearance required", and "customs clearance".
- On the fixtures, all 10 text-only USAJobs citizenship postings and the 1 structured one are caught. Two USAJobs postings stay `ambiguous` (see Surprises).
- The idempotency test runs the step twice over the Adzuna and USAJobs fixtures and gets an identical table apart from `classified_at`.

**4. Outlook view and scan.**
- `v_job_visa_outlook` covers in-scope jobs and includes `bucket` plus a `bucket_reason` naming the rule that fired.
- The scan prints one evidence block per job. It selects an explicit `OUTPUT_COLUMNS` list containing only employer-level aggregates, and `--csv` writes the same columns.
- Tests cover one job per bucket, precedence (a cap-exempt university with "must be a U.S. citizen" is closed, and a 3-LCA employer whose posting says "unable to sponsor" is closed), an employer below the threshold landing in possible, and output containing no case numbers.

**5. Docs.** Every new table, column and view, and each judgment call, is in `docs/data_dictionary.md` under "Visa-sponsorship layer". The owner workflow and the "What this can't tell you" section are in `src/visa/README.md`.

## Parked questions

| Q | Question | Recommendation (built) |
|---|---|---|
| 1 | Create views from migrations instead of a helper? | (a) keep `make views` |
| 2 | Confirm the analytics SOC list | (a) keep the 8 codes, revisit with real counts |
| 3 | Outlook bucket thresholds | (a) keep defaults until the first real scan |
| 4 | Anchor of the "last 3 FYs" window | (a) data-relative (latest loaded FY) |
| 5 | Count Certified-Withdrawn as certified? | (a) no |
| 6 | Is "Public Trust" a restriction? | (a) no, record the mention |
| 7 | Cap-exempt: hospitals, research nonprofits, government labs | (a) unknown for now; (b) next |
| 8 | How to add the USCIS H-1B Employer Data Hub | (a) separate manual-download loader, same key |
| 9 | HigherEdJobs RSS source | (a) wait for a saved feed sample |
| 10 | Lowercase "must be a us citizen" | (a) stays ambiguous |
| 11 | Out-of-order loads ("latest load wins") | (a) keep, document load order |

### Q1. Views: helper or migrations?
- **What I found:** no migration, test, script or Makefile target created the views, so a fresh `alembic upgrade head` database had none. The four existing views are independent, and the new outlook view depends on the sponsorship view.
- **Options:**
  - (a) `scripts/apply_views.py` + `make views`, re-run after view changes.
  - (b) An Alembic migration per view change, with `op.execute(open(file).read())`. Views would then be versioned with the schema, but every edit needs a migration and downgrades need the previous SQL.
  - (c) Both: the helper for development, plus one migration that calls it.
- **Recommendation:** (a), built. It fits the "views are source of truth, re-run freely" style. Reconsider (b) once views are deployed somewhere that only runs migrations (Phase 6).

### Q2. Analytics SOC list
- **What I found:** the brief's default list, matched on `LEFT(soc_code, 7)`, so 15-2051.01 BI Analysts counts under 15-2051. 13-1111 Management Analysts, 15-1211 Computer Systems Analysts and 13-2051 Financial Analysts are broad, and large consultancies and staffing firms file heavily under them.
- **Options:**
  - (a) Keep all 8.
  - (b) Narrow to the core data codes 15-2051, 15-2041, 15-2031 and 13-1161, and report the broad codes separately.
  - (c) Add more, such as 15-1252 Software Developers for analytics-engineering roles.
- **Recommendation:** (a), built. After the first real load, compare `certified_h1b_analytics_soc` with and without the broad codes for a few employers you know. The list lives only in the view's `analytics_soc` CTE.

### Q3. Bucket thresholds
- **What I found:** the defaults are: strong = `will_sponsor`, or ≥ 3 certified analytics-SOC new-employment H-1B LCAs in the last 3 FYs, or cap-exempt hint; possible = any certified H-1B LCA in the last 3 FYs. Three filings is a low bar for a big employer, and the cap-exempt hint is name-only but still lifts a job to strong.
- **Options:**
  - (a) Keep the defaults.
  - (b) Raise the LCA bar (e.g. ≥ 10, or a share of filings), and/or move cap-exempt into its own `strong_cap_exempt` bucket.
  - (c) Weight by wage level, given the FY2027 weighted lottery.
- **Recommendation:** (a), built. Revisit after the first real scan. All thresholds are in one `CASE` in `v_job_visa_outlook.sql`.

### Q4. "Last 3 FYs" anchor
- **What I found:** a window anchored on today's date would silently shrink when the newest file hasn't been loaded yet.
- **Options:**
  - (a) Data-relative: `MAX(fiscal_year)` loaded and the two before it.
  - (b) Calendar-relative: the current federal FY and the two before it.
  - (c) Make it a parameter.
- **Recommendation:** (a), built. It is deterministic and recomputable, and `window_start_fy` and `window_end_fy` are printed by the scan so the window stays visible.

### Q5. Certified-Withdrawn
- **What I found:** these filings were certified, then withdrawn by the employer. They show intent but not a live position.
- **Options:**
  - (a) Exclude them from "certified".
  - (b) Include them.
  - (c) Add a separate column.
- **Recommendation:** (a), built. `n_lcas_all_statuses` keeps the unfiltered total.

### Q6. Public Trust
- **What I found:** Public Trust is a suitability determination, not a security clearance. Whether non-citizens can hold one depends on the agency and contract. Federal postings usually carry a separate citizenship requirement, which is caught on its own.
- **Options:**
  - (a) Not a restriction, with the mention recorded as the reason.
  - (b) A restriction.
  - (c) A new `restriction = 'public_trust'` value.
- **Recommendation:** (a), built. Choose (c) if real scans show many Public Trust postings with no other signal.

### Q7. Cap-exempt beyond universities
- **What I found:** the brief limits `likely` to University, College, Community College and Institute of Technology without a for-profit marker. Affiliated hospitals, nonprofit research organisations and government research organisations can also be exempt, but you can't tell from a name, and committing a list of real employers isn't allowed.
- **Options:**
  - (a) Keep these as `unknown`. Hospitals, medical centres, health systems and labs get a "parked entity type" reason.
  - (b) A local, gitignored `data/cap_exempt_allowlist.txt` of employer keys you have verified yourself, read by the classifier when present.
  - (c) Infer from NAICS codes in `lca_cases` (e.g. 611310 Colleges and Universities, 5417 research). This would be an LCA-side hint keyed on `employer_key`.
- **Recommendation:** (a) now, built. (b) next, because it keeps real names out of the repo. (c) is a reasonable secondary hint later, but it needs a trap test for for-profit schools that use NAICS 611310.

### Q8. USCIS H-1B Employer Data Hub
- **What I found:** it is out of scope here. It publishes petition-level approvals and denials (initial and continuing) by employer and FY. That is closer to "actually sponsored" than LCAs.
- **Options:**
  - (a) A separate manual-download loader into `uscis_h1b_employers`, keyed by `normalize_company_name`, with the same allowlist and upsert pattern. Add its counts as extra columns in `v_employer_sponsorship` and its own evidence line in the scan.
  - (b) Replace LCAs with it.
  - (c) Skip it.
- **Recommendation:** (a). LCAs give the role and wage detail (SOC, wage level) and USCIS gives outcomes, so they complement each other.

### Q9. HigherEdJobs RSS source
- **What I found:** it is out of scope here, and it needs a real feed sample to design a parser against. Fetching one wasn't allowed.
- **Options:**
  - (a) You save one feed response locally under `data/`, then a later session builds a parser against a synthetic fixture that mirrors its shape.
  - (b) Skip it, since universities already reach the scan through Adzuna.
- **Recommendation:** (a). University postings are the main cap-exempt route, and Adzuna's 500-character cap hides their visa language.

### Q10. Lowercase "us citizen"
- **What I found:** to avoid the pronoun ("help us persuade…"), "US" is matched in uppercase only. So "must be a us citizen" lands as `ambiguous`, not `citizenship`.
- **Options:**
  - (a) Keep it.
  - (b) Also accept lowercase "us" directly after "must be a/an" (low false-positive risk), with a trap test.
- **Recommendation:** (a), built. Switch to (b) if the real scan shows a noticeable number of `ambiguous: … us citizen` reasons. `restriction_reason` makes them easy to count.

### Q11. Out-of-order loads
- **What I found:** "latest load wins" means loading FY2026 Q3 after FY2026 Q4 would overwrite Q4's statuses with older ones.
- **Options:**
  - (a) Keep it and document "load in chronological order".
  - (b) Only overwrite when the incoming row's `decision_date` (or the file's quarter) is newer.
- **Recommendation:** (a), built. Documented in the loader docstring, the data dictionary and `src/visa/README.md`.

## What needs a local run from the owner

This repo has no browser pass and nothing was fetched, so you need to download the files and run the steps:

```bash
git fetch origin && git checkout claude/visa-sponsorship-layer
pip install -e ".[dev]"                      # picks up openpyxl
# .env: DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/jobmarket

# 1. schema
alembic upgrade head                         # adds lca_cases, job_visa_signals

# 2. download by hand from DOL OFLC's "Performance Data" page:
#    LCA Programs (H-1B, H-1B1, E-3) disclosure data, the LATEST quarter of each FY
mkdir -p data/lca                            # gitignored
#    e.g. data/lca/LCA_Disclosure_Data_FY2024_Q4.xlsx, ..._FY2025_Q4.xlsx, ..._FY2026_Q4.xlsx

# 3. load (dry-run first; then in chronological order)
python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2026_Q4.xlsx --fiscal-year 2026 --dry-run
python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2024_Q4.xlsx --fiscal-year 2024
python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2025_Q4.xlsx --fiscal-year 2025
python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2026_Q4.xlsx --fiscal-year 2026

# 4. views (all six) on the real database
make views

# 5. posting signals
python -m src.cleaning.apply_cleaning --only companies visa

# 6. match review
python -m src.visa.sponsor_match             # -> data/sponsor_match_candidates.csv
#    mark `approved`, promote approved pairs into src/cleaning/data/company_aliases.json, then:
python -m src.cleaning.apply_cleaning --only companies
python -m src.visa.lca_loader --rekey

# 7. scan
python -m src.visa.scan --limit 50
python -m src.visa.scan --bucket strong --metro NYC --csv data/visa_scan.csv
```

**Sanity checks:**
- **Loader output.** "allowlisted columns absent" should be empty. If it isn't, DOL renamed a header that year, so tell the next session which one. `bad cells nulled` should be a tiny fraction of rows read. `by case_status` should be mostly Certified and `by visa_class` mostly H-1B. "duplicate CASE_NUMBERs within file" should be about 0.
- **Cumulative reload.** Loading Q3 and then Q4 of the same FY should leave `select count(*) from lca_cases where fiscal_year = <FY>` equal to the Q4 file's row count, not the sum.
- **Employers you know.** Take 3–5 employers you know sponsor. Compare their `last_3_fy` `certified_h1b_lcas` with what myvisajobs or h1bdata show (they are built on the same DOL files, so the numbers should be in the same ballpark, though their windows and dedup differ). Also check that `median_offered_annual_wage` looks plausible.
- **Match rate.** Run `select employer_matched, count(*) from v_job_visa_outlook group by 1`. A low match rate means the alias review is worth doing.
- **Bucket mix.** Run `select bucket, count(*) from v_job_visa_outlook group by 1`. Expect most USAJobs jobs in closed, since federal jobs require citizenship, and many Adzuna jobs in unknown, because of truncated text.
- **Ambiguous rows.** Run `select restriction_reason, sponsorship_reason from job_visa_signals where restriction_reason like 'ambiguous%' or sponsorship_reason like 'ambiguous%'`. These are the phrases the rules couldn't read. Each one is a candidate for a new rule, which needs a trap test first.

## Surprises

- **Branch.** This cloud session's harness named `claude/inspiring-tesla-jvpvdw` as the development branch, but the brief says `claude/visa-sponsorship-layer`. I followed the brief, because you asked for it to be followed exactly. Nothing was pushed to the harness branch or to `main`.
- **`%` in view comments.** The existing views' header comments contain `%` ("PRESENT% column"). That breaks `exec_driver_sql` under psycopg2 (`immutabledict is not a sequence`), so the helper runs each file through a raw cursor with no parameters. Anyone who later moves views into migrations will hit the same issue.
- **README in the diff.** GitHub and `git diff --stat` show README.md as `Bin` → text in this diff, because main's copy was binary (the NULs). It is plain UTF-8 now.
- **Two ambiguous USAJobs postings.** The fixture contained "Who May Apply: US Citizens", which no initial rule read. I added a trap-tested rule for it. "Preference Eligible United States Citizen Applying to a DCIPS Position" stays ambiguous by design.
- **`employer_key` computed at load time.** It is set when a file loads, so alias edits wouldn't reach `lca_cases` without reloading 100 MB files. I added `lca_loader --rekey` (commit 4b) to keep the layer recomputable.
- **Exact matches skipped.** The match finder skips a company whose key already exactly matches an LCA key, even if a longer sibling key exists (e.g. `fakeco` and `fakeco analytics`). Those siblings are never proposed. That is deliberate (the join already has evidence), but say so if you want siblings listed too.

## Suggested PR title

**Visa-sponsorship layer: DOL LCA history, posting-text signals, and an F-1/OPT outlook scan**

<details>
<summary>PR description (ready to paste)</summary>

## Summary

Adds a visa-sponsorship layer that tells an F-1 OPT holder who will later need H-1B sponsorship how open each in-scope job is, and shows the evidence. It combines three independent signals in one view (`v_job_visa_outlook`) and one CLI (`python -m src.visa.scan`):

1. **Employer history**: DOL LCA disclosure files are loaded through an explicit column allowlist into `lca_cases` and aggregated in `v_employer_sponsorship` (certified H-1B, new-employment and analytics-SOC subsets, wage-level mix, median offered annual wage, H-1B-dependent and willful-violator flags; per FY and for the last 3 FYs).
2. **Posting text**: `job_visa_signals` records citizenship or clearance restrictions, will or won't sponsor, OPT/CPT mentions and text coverage, each with its reason. USAJobs' structured KeyRequirements beats text.
3. **Cap-exempt hint**: from the company name only (university or college without a for-profit marker).

Buckets, in order: closed → strong → possible → unknown, with a `bucket_reason`.

Also:
- `reset_schema` now refuses non-local or non-"test" databases.
- URLs name the psycopg2 driver.
- README.md's NUL bytes are removed.
- `make views` (`scripts/apply_views.py`) applies every view in order in one transaction.

## Design rules followed
- Flag, don't guess: unreadable phrases become `none_found` with `ambiguous: <phrase>`. `none_found` on truncated (Adzuna) text means unknown, never "sponsors".
- Precision over recall: every rule has a trap test in `tests/test_posting_signals.py`.
- Layer, don't destroy: nothing raw is modified. Company ↔ LCA matches go to `data/sponsor_match_candidates.csv` for manual review and are never auto-merged.
- Recomputable: the `visa` step rebuilds idempotently, and `lca_loader --rekey` re-keys after alias edits.
- No real data committed: every fixture is synthetic, with FAKE names. Personal-data LCA columns are never loaded, which is tested.

## Testing
- `pytest` with `TEST_DATABASE_URL`: 182 → **310 passed**, 0 failed, 0 skipped
- `ruff check .` is clean, and every changed .py file is formatted
- `alembic upgrade head && downgrade base && upgrade head` is clean
- `make views` applies all six views to a fresh alembic-built DB, twice

## Open questions
11 parked product decisions are in `docs/overnight-visa-layer.md`, each with options and the default that was built. They cover the SOC list, bucket thresholds, the window anchor, Public Trust, cap-exempt scope, the USCIS Data Hub, HigherEdJobs, and views via migrations.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01ATh4ABgiML8G58MzgJ36ZP

</details>
