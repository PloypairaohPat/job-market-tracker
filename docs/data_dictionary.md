# Data Dictionary — Schema v1 (Phase 1)

Every table, every column, what populates it, and — most importantly — **every judgment call baked into the data**. Downstream analysis is only as trustworthy as the definitions here. Updated with every migration.

Conventions used throughout:
- **Flag, don't guess**: ambiguous or missing source values become `NULL`, never inferred defaults.
- **Store as-is in Phase 1**: no normalization of names, titles, or locations yet; Phase 2 adds normalization *as a layer*, never destructively.
- All timestamps are `timestamptz` (UTC).

---

## `raw_responses` — verbatim API call results

The project's insurance policy. Every API response is stored here *before* any parsing, so cleaning logic can be re-run against history without re-fetching. Grows monotonically by design (every fetch is evidence); will be partitioned by date if size warrants (Phase 6+).

| Column | Type | Meaning / populated by |
|---|---|---|
| `id` | serial PK | |
| `source` | text | `'adzuna'` (later: `'usajobs'`, `'greenhouse'`) |
| `fetched_at` | timestamptz | server default `now()` at insert |
| `endpoint` | text | API path fetched, e.g. `/jobs/us/search/1` |
| `params` | jsonb | query params **excluding credentials** |
| `response` | jsonb | the full response body, byte-for-byte as parsed JSON |

Index: `(source, fetched_at)` — the dominant access pattern is "replay source X over date range Y".

---

## `companies` — company entities (unnormalized in Phase 1)

| Column | Type | Meaning / judgment calls |
|---|---|---|
| `id` | serial PK | |
| `canonical_name` | text, unique | **Phase 1: the exact string from the API.** True canonicalization ("Meta Platforms Inc" → "Meta") is Phase 2; until then this column's name is aspirational. |
| `raw_names` | text[] | every raw variant observed; currently `[canonical_name]`. Phase 2 merges rows and unions these arrays — the raw strings are never lost. |
| `industry` | text, null | not populated in Phase 1 |
| `size_bucket` | text, null | not populated in Phase 1 (`'1-50'`, `'51-200'`, …) |
| `created_at` | timestamptz | first time this name was seen |

**Known limitation**: postings with no company in the source are stored with `jobs.company_id = NULL` — no "Unknown" placeholder row, so company-level aggregates silently exclude them. Measure the fraction in every analysis.

---

## `locations` — location entities

Populated from Adzuna's hierarchical `location.area` array (broadest first): `country = area[0]`, `state = area[1]` if present, `city = area[last]` if the array goes deeper than two levels. Arrays vary in depth — country-only and state-only rows are real and expected.

| Column | Type | Meaning / judgment calls |
|---|---|---|
| `id` | serial PK | |
| `city` | text, null | `NULL` when the source only gave country/state |
| `state` | text, null | |
| `country` | text, null | |
| `metro_area` | text, null | not populated in Phase 1; Phase 2 assigns `'NYC'`, `'SF Bay Area'`, etc. |
| `is_remote` | bool | crude Phase 1 signal, see `jobs.is_remote` |
| `latitude`, `longitude` | numeric(9,6), null | passed through when the API provides them |

Uniqueness: `(city, state, country)`. **Gotcha**: Postgres treats NULLs as distinct in unique constraints, so the ingestion upsert does an explicit select-then-insert to keep `('US','Virginia',NULL)` a single row. Covered by an integration test.

---

## `jobs` — one row per unique posting

Natural key: **`(source, external_id)`** — Adzuna IDs are only guaranteed unique within Adzuna. Re-ingestion updates mutable fields and `last_seen_at`; it never duplicates and never touches `first_seen_at`.

| Column | Type | Meaning / judgment calls |
|---|---|---|
| `id` | serial PK | internal ID; use this in joins, not `external_id` |
| `external_id` | text | ID from the source system |
| `source` | text | `'adzuna'` |
| `company_id` | int FK, null | `NULL` = source posting had no company |
| `location_id` | int FK, null | `NULL` = source posting had no parsable location |
| `title` | text | exactly as posted |
| `title_normalized` | text | **lowercase + whitespace-collapse only.** No seniority stripping, no role clustering — that's Phase 2. |
| `seniority` | text, null | not populated in Phase 1 |
| `description` | text, null | as provided (Adzuna truncates long descriptions — a known source limitation affecting Phase 2 skill extraction recall) |
| `description_full` | text, null | *(added Phase 2 prep)* untruncated text when available — from a source that doesn't truncate (USAJobs) or a future second-pass fetch. `description` is never overwritten; `src/cleaning/extract_skills.py` prefers this column when present, falling back to `description`. See "USAJobs source notes" below for how it's composed. |
| `salary_min`, `salary_max` | int, null | `NULL` = not disclosed. **Never zero-filled.** |
| `salary_currency` | text, null | `'USD'` when salary present (US endpoint); `NULL` otherwise |
| `salary_period` | text, null | `'year'` when salary present — Adzuna US returns annualized figures. **Caveat**: suspected hourly-as-annual contamination in the low tail (see phase 1 findings); Phase 2 adds a quality flag. |
| `salary_is_predicted` | bool, null | `true` = the figure is **Adzuna's model estimate**, not employer-disclosed. Must be separable in every salary analysis. |
| `is_remote` | bool | Phase 1 signal = word-boundary `remote` in title or location display name. **A floor, not an estimate** — description-level detection is Phase 2. |
| `category` | text, null | Adzuna category label, e.g. `'IT Jobs'`. For USAJobs *(Phase 2 prep)*: every `JobCategory` label, semicolon-joined (a posting can carry more than one) — see "jobs.category now joins every label" below |
| `in_scope` | bool, null | *(added Phase 2 prep)* `NULL` = not yet classified. Relevance flag — see "jobs.in_scope / jobs.scope_reason" below. Filter analyses with `WHERE in_scope` |
| `scope_reason` | text, null | *(added Phase 2 prep)* always set alongside `in_scope`; makes the classification auditable and revisitable |
| `contract_type` | text, null | `'permanent'` / `'contract'` when provided |
| `contract_time` | text, null | `'full_time'` / `'part_time'` when provided |
| `redirect_url` | text, null | Adzuna landing URL for the posting |
| `posted_at` | timestamptz, null | Adzuna's `created` — may reflect aggregation time rather than original posting time; treat with suspicion until compared against `first_seen_at` |
| `first_seen_at` | timestamptz | when *our* pipeline first observed the job; immutable after insert |
| `last_seen_at` | timestamptz | refreshed on every re-observation |
| `removed_at` | timestamptz, null | set by a future lifecycle job when a posting stops appearing; **cleared** if the job reappears |
| `raw_response_id` | int FK | the raw page this row was last parsed from — the audit trail back to source |

Fields refreshed on re-observation: title, description, salary fields, remote flag, category, contract fields, URL. Identity fields and `first_seen_at` are never updated.

---

## `job_snapshots` — daily observed state per job

One row per `(job_id, snapshot_date)`, written on every ingestion run that observes the job. This is what makes time-series analysis possible; capture starts in Phase 1 (deliberately ahead of the original plan) so the 90-day accumulation target isn't gated on Phase 2.

| Column | Type | Meaning |
|---|---|---|
| `job_id` | int FK, PK | |
| `snapshot_date` | date, PK | UTC date of observation |
| `is_active` | bool | `true` when observed; a future lifecycle job writes `false` rows for disappearances |
| `salary_min`, `salary_max` | int, null | salary *as of that day* — captures mid-lifetime salary changes |

**Semantics note**: absence of a row for a date means "not observed that day", which is not identical to "inactive" (the job may simply not have matched any search query that day). Interpret gaps carefully; Phase 3 defines the analytical treatment.

---

## Cross-cutting facts analysts must know

1. **Per-query counts don't sum to the jobs total.** The same posting matches multiple search queries; upserts dedupe it into one row. This is correct behavior, not data loss.
2. **`raw_responses` grows on every run; nothing else duplicates.** If `jobs` counts rise on an immediate re-run, that's a bug (and a failing test).
3. **The dataset only contains what the six target queries return.** It is a view of the *analyst job market as reachable through those queries on Adzuna*, not the labor market as a whole. Selection effects apply to every conclusion.

---

## `skills` — skill taxonomy *(added in Phase 2 prep)*

Materialization of the curated taxonomy in `src/cleaning/data/skills.json` — **the JSON file is the source of truth** (reviewable in diffs); the table is synced by `python -m src.cleaning.extract_skills`.

| Column | Type | Meaning |
|---|---|---|
| `id` | serial PK | |
| `name` | text, unique | canonical display name (`'Python'`, `'Power BI'`) — aliases resolve here, so co-occurrence analysis never double-counts |
| `category` | text | `language` \| `database` \| `bi_tool` \| `data_tool` \| `cloud` \| `ml_stats` \| `workflow` \| `soft` |
| `aliases` | text[] | reserved; alias matching currently lives in the taxonomy JSON patterns |

## `job_skills` — job ↔ skill links *(added in Phase 2 prep)*

Written by regex-based extraction over `title + description`. **A derived layer**: it can always be rebuilt from stored descriptions (`--rebuild`), which is the raw-then-normalized pattern applied to NLP.

| Column | Type | Meaning / judgment calls |
|---|---|---|
| `job_id` | int FK, PK | |
| `skill_id` | int FK, PK | |
| `confidence` | numeric(3,2) | pattern-level confidence from the taxonomy, **not** a per-mention probability. `1.0` = unambiguous term (`Tableau`); `< 1.0` = term needing case/context anchoring (`R` 0.8, `Excel` 0.9, soft skills 0.5–0.7). Filter with `WHERE confidence >= x` per analysis. |

**Extraction philosophy — precision over recall.** Ambiguous terms only match with case-sensitive or context-anchored patterns ("in R", "Python/R" — never bare `R`, so "HR" and "R&D" can't false-positive). A missed mention costs a little recall; a false positive silently corrupts every downstream skill analysis. Every ambiguous term has a false-positive trap test in `tests/test_skill_extractor.py` — **when adding a skill, write its trap case first**.

**Known recall limits** (documented, accepted for now): Adzuna truncates descriptions, capping recall regardless of extractor quality; and spaCy-based patterns (Phase 2 proper) will be measured against a manual audit of a random sample before adoption.

---

## USAJobs source notes *(added in Phase 2 prep)*

USAJobs (`jobs.source = 'usajobs'`) returns full, untruncated text via its
official API — no ToS or scraping concerns, unlike the redirect-URL
enrichment path evaluated and rejected for Adzuna (see `phase_1_findings.md`).
Parsing lives in `src/ingestion/usajobs_parser.py`; every judgment call below
was made against a real sample response (`docs/usajobs_sample_response.json`),
not guessed from documentation alone.

- **`external_id` is `MatchedObjectId`, not `PositionID`.** `PositionID`
  (e.g. `"FD-2026-0027"`) is the hiring agency's own announcement number —
  human-readable but agency-assigned, not guaranteed unique across agencies.
  `MatchedObjectId` is USAJobs' own system key.
- **`companies.canonical_name` = `DepartmentName`** (cabinet-level agency,
  e.g. "Department of Homeland Security"), not `OrganizationName`
  (sub-component, e.g. "Federal Emergency Management Agency"). Coarser, but
  keeps `companies` from fragmenting into hundreds of internal office names.
  `OrganizationName` is not currently captured anywhere.
- **`location_id` is `NULL` whenever a posting has anything other than
  exactly one `PositionLocation` entry.** Real postings can list dozens or
  hundreds of locations ("Nationwide" postings); picking one arbitrarily
  would fabricate a specific location the posting doesn't actually have.
  This extends the existing "NULL = no parsable location" semantics to
  "no *single* parsable location" — an accepted recall cost, not a bug.
- **USAJobs location fields are cross-source inconsistent, stored as-is.**
  `CountryCode` holds the full country name ("United States") and
  `CountrySubDivisionCode` the full state name ("Maryland") — despite the
  field names, neither is an abbreviated code like Adzuna's `"US"`. Phase
  1/2-prep philosophy is store-what-the-source-gives, don't normalize across
  sources yet — so `locations.country`/`state` will contain both styles
  until a real cross-source normalization layer exists. `city` is derived by
  stripping the `", {state}"` suffix USAJobs redundantly appends to
  `CityName`.
- **`description_full` concatenates only narrative fields**: `JobSummary`,
  `MajorDuties`, `Education`, `Requirements`, and the top-level
  `QualificationSummary` (which, unlike the others, does not live under
  `UserArea.Details`). Deliberately excludes application-process fields
  (`HowToApply`, `RequiredDocuments`, `Benefits`, `OtherInformation`) that
  would dilute skill-extraction signal with "submit your resume by..."
  boilerplate. `description` gets the short `JobSummary` field alone — not
  truncated by USAJobs, just naturally brief (confirmed against a live
  25-result sample: lengths 55–500, and the two that happened to land at
  exactly 500 both end on a complete sentence, unlike Adzuna's mid-word cut).
- **`salary_period` only maps codes verified against USAJobs' own codelist**
  (`GET /api/codelist/remunerationrateintervalcodes`): `PA`→`year`,
  `PH`→`hour`, `PM`→`month`. Real but unmapped codes (`BW` biweekly, `PD`
  daily, `FB`, `PW`, `ST`, `SY`, `WC`) leave `salary_period` `NULL` while
  still storing the disclosed `salary_min`/`salary_max` — flag, don't guess.
  `salary_is_predicted` is always `False` for this source (federal pay bands
  are employer-disclosed, never a modeled estimate).
- **`contract_time`/`contract_type` only map codes verified against
  USAJobs' codelists** (`positionscheduletypes`, `positionofferingtypes`):
  schedule `1`→`full_time`, `2`→`part_time`; offering `15317`→`permanent`.
  The many other offering types (Temporary, Term, Seasonal, Internships,
  Telework, ...) don't collapse cleanly onto Adzuna's binary
  permanent/contract vocabulary and are left `NULL` rather than
  force-fitted into a misleading bucket.

## `jobs.in_scope` / `jobs.scope_reason` — relevance classification *(added in Phase 2 prep)*

**Problem, backed by real data.** Federal keyword search is badly polluted: "analyst" matches
Budget Analysts, Intelligence Specialists, Procurement Analysts, Accountants, and Engineers
alongside genuine data-analytics roles. Of 183 USAJobs postings ingested by keyword, only 28
are genuinely data-analytics roles once classified (see below) — every unfiltered federal skill
statistic was measuring analytics-skill density across a population that's mostly non-analytics
jobs.

**Policy: flag, never delete.** Every job keeps its row regardless of relevance; `in_scope`
(nullable bool, `NULL` = not yet classified) and `scope_reason` (text, always set alongside
`in_scope`) make the filter auditable and revisitable — analyses use `WHERE in_scope`, exactly
like `salary_quality`. Classification logic lives in `src/cleaning/scope_classifier.py`
(`python -m src.cleaning.apply_cleaning --only scope`), recomputable at any time from stored
`category`/`description`/`description_full` — no re-fetch needed.

**Source-agnostic design, currently source-differentiated in practice:**
- Any non-USAJobs source (currently just Adzuna) → always `in_scope=True`,
  `scope_reason='non_usajobs_default'`. Commercial keyword search is far less polluted;
  reconsider only if real data says otherwise.
- USAJobs → category-based. `jobs.category` can hold multiple semicolon-joined labels (see
  below) — a posting counts as in-scope if *any* label qualifies:
  - **Clean in-scope** (`CLEAN_IN_SCOPE_CATEGORIES`): Data Science Series, Operations Research,
    Statistics — confirmed unambiguously quantitative via `GET /api/codelist/occupationalseries`.
    Passes regardless of description content.
  - **Ambiguous, skill-density tie-break** (`AMBIGUOUS_CATEGORIES`): Management And Program
    Analysis, Information Technology Management — federal generalist-analyst catch-alls.
    Tie-broken by counting distinct skills the existing `SkillExtractor` finds in
    `title + (description_full or description)`, restricted to the `language`/`database`/
    `bi_tool`/`data_tool`/`ml_stats` taxonomy categories (excludes `cloud`/`workflow`/`soft` —
    weaker standalone signals). Threshold: **≥2** distinct skills. Empirically validated against
    the real 66-job Management-And-Program-Analysis bucket before adoption: distribution was
    0→40, 1→12, 2→8, 3→5, 4→1 jobs; ≥2 yields 14 in-scope (titles like "Data Analyst" and
    "Program Analyst (Informatics)" correctly pass; generic "MANAGEMENT ANALYST" and bare
    "Program Analyst" — 0 skills — correctly fail).
  - **Everything else** → out of scope by default, `scope_reason='category_excluded:<category>'`.
    A posting with no category at all → out of scope (`'no_category'`) — no signal to include it
    on, flag don't guess.
  - `scope_reason` values: `'series:<label>'`, `'skill_density:<label>:<n>'`, or
    `'category_excluded:<category>'` / `'no_category'`.

**Real classification result** (full 183-row USAJobs population, run 2026-08-31): **28 in-scope**
— 14 via `series:Operations Research`, 8 via `skill_density:...:2`, 5 via `:3`, 1 via `:4`; 155
out of scope. Lands close to an independent ~10–25 estimate, and every row is auditable via
`scope_reason` rather than silently discarded.

### `jobs.category` now joins *every* label, not just the first

Discovered during this work: a posting can carry multiple `JobCategory` entries (confirmed live,
~4% of a real sample) — e.g. job `865002200`, "INTERDISCIPLINARY GENERAL ENGINEER/OPERATIONS
RESEARCH ANALYST", is tagged both General Engineering *and* Operations Research. The original
parser kept only `categories[0]`, so this real Operations Research role was stored as
`"General Engineering"` and would have been silently excluded by a category-only classifier.
Fixed in `usajobs_parser._parse_category` to join all labels, semicolon-delimited
(`usajobs_parser.split_categories` reverses it). The 183 already-ingested rows were corrected via
`python -m src.ingestion.ingest_usajobs --backfill-from-raw` — re-parses stored `raw_responses`
without any network call (raw-then-normalized applied to a parser bugfix); does not touch
`job_snapshots` or create new `raw_responses` rows, since it's a data-repair pass, not a new
observation. Result: `jobs.category` now has 9 multi-label rows (was architecturally impossible
to represent before), and the Operations Research in-scope count rose from 9 (single-label) to 14
(any-label).

## Series-code ingestion *(added in Phase 2 prep)*

`ingest_usajobs.py` can query USAJobs by occupational series code (`JobCategoryCode`) directly,
in addition to keyword search — confirmed live this finds postings keyword search structurally
cannot: `JobCategoryCode=1560` (Data Science) alone returns 23 real results, while
`Keyword=data analyst`+`JobCategoryCode=1560` returns **zero** — those postings' searchable text
doesn't contain "data analyst" as a phrase.

- `TARGET_SERIES_CODES = ["1560", "1515", "1530"]` (Data Science, Operations Research,
  Statistics) — the 3 series confirmed unambiguously clean. **Deliberately excludes** 0343
  (Management And Program Analysis) and 2210 (IT Management): confirmed live that neither gets
  cleaner via series-code querying — `JobCategoryCode=0343` alone is 323 open postings
  system-wide, and even `Keyword=data`+`0343` stays at 229. Query-time filtering can't fix these;
  they're handled by the relevance layer above instead.
- `run_ingestion(..., series_codes=...)` is **opt-in** (defaults to `None` = skip), unlike
  `queries` (defaults to `TARGET_QUERIES`) — a new capability shouldn't silently change behavior
  for existing callers. `main()`'s `--series-codes` flag defaults to `TARGET_SERIES_CODES` so real
  CLI runs get it by default; the underlying function requires an explicit argument.
- Counts dict keys: keyword searches keep the plain query string (unchanged); series searches use
  `"series:<code>"`.

## Cleaning-layer columns *(added in Phase 2 prep)*

All populated by `python -m src.cleaning.apply_cleaning` — idempotent, derived entirely from stored raw values, recomputable after any rule change.

### `jobs.seniority`
`'junior' | 'mid' | 'senior' | 'lead' | NULL` from title patterns. **NULL means no signal, never "mid"** — a bare "Data Analyst" carries no seniority information and forcing a bucket would fabricate data. Judgment calls: "Associate Director" is `lead` (not junior); lead/principal/staff/head/director/manager share one bucket; precedence is lead > senior > mid > junior. Full rules + trap tests: `src/cleaning/seniority.py`, `tests/test_cleaning.py`.

### `jobs.salary_quality`
`NULL` (no salary disclosed) `| 'ok' | 'suspect_hourly_as_annual' | 'suspect_inverted' | 'suspect_outlier_high'`. Raw salary values are **never modified or discarded** — analyses choose their own inclusion rule (typically `WHERE salary_quality = 'ok'`). Thresholds live in ONE place (`salary_quality.py`: hourly ceiling $25k, outlier floor $500k) and get tuned there after real-data audits, never inline in analyses. Note `salary_is_predicted` is orthogonal: an Adzuna estimate can still be `'ok'` quality — filter on both dimensions deliberately.

### `jobs.is_remote` (upgraded semantics)
Phase 2 policy: title/location "remote" is a strong signal that wins over hybrid language in descriptions; description positives ("fully remote", "work from home") count only absent negation/hybrid patterns. **Hybrid is not remote** — this flag tracks fully-remote eligibility only.

### `locations.metro_area`
`'NYC' | 'SF Bay Area' | 'LA' | 'Chicago' | 'Boston' | 'Seattle' | 'Austin' | 'DC' | NULL`. City-list based (explicit, auditable; a missing suburb is a one-line fix). DC added beyond the original guide list — it's a top analytics market via federal/contractor demand and the planned USAJobs source skews there. Disambiguation traps handled: Washington-the-city requires DC state; only Virginia's Springfield is claimed. NULL = not in a tracked metro (distinct from unknown location).

### `companies.normalized_name`
Lowercase **grouping key** from the three-tier normalization layer: deterministic rules (legal-suffix stripping, "The" prefix, punctuation) → curated aliases (`src/cleaning/data/company_aliases.json`, e.g. facebook→meta) → fuzzy candidates written to `data/company_merge_candidates.csv` for **manual review, never auto-merged**. Approved pairs get promoted into the alias file, making review output durable and versioned. Display names for reporting are chosen at query time (most frequent raw name per key); `canonical_name`/`raw_names` are never modified.

---

## Visa-sponsorship layer *(added with the visa layer)*

How open each in-scope job is to someone on **F-1 OPT who will later need H-1B sponsorship**, with the evidence. Three independent signals: the employer's DOL LCA filing history, what the posting text says, and a name-only cap-exempt hint. How-to and caveats: [`src/visa/README.md`](../src/visa/README.md). Open product decisions: [`docs/overnight-visa-layer.md`](overnight-visa-layer.md).

### `lca_cases` — DOL Labor Condition Applications

Loaded by `python -m src.visa.lca_loader --file data/lca/<file> --fiscal-year <FY>` from the Office of Foreign Labor Certification's quarterly LCA disclosure files (.xlsx or .csv). **One row = one LCA filing, not one approved H-1B and not one hire.** The source files are never committed (`data/` is gitignored).

| Column | Type | Meaning / judgment calls |
|---|---|---|
| `case_number` | text PK | `CASE_NUMBER`. Upsert key: files are cumulative within a fiscal year (Q3 contains Q1+Q2), so loading Q2 then Q3 converges instead of double counting. **The latest load wins** for every column — load files in chronological order. Duplicates within one file: last occurrence kept, counted. Rows without a case number: skipped, counted. |
| `case_status` | text | `Certified` \| `Certified-Withdrawn` \| `Denied` \| `Withdrawn`, as given |
| `received_date`, `decision_date`, `begin_date` | date, null | parsed from Excel dates, ISO or `m/d/Y`; unparseable → NULL, counted |
| `visa_class` | text | `H-1B` \| `E-3 Australian` \| `H-1B1 Chile` \| `H-1B1 Singapore` |
| `job_title`, `soc_code`, `soc_title` | text | as given. `soc_code` keeps its `.01`-style detail suffix; views match on `LEFT(soc_code, 7)` |
| `full_time_position`, `h1b_dependent` (`H-1B_DEPENDENT`), `willful_violator` | bool, null | `Y`/`Yes`/`N`/`No` (any case); blank → NULL; anything else → NULL, counted |
| `total_worker_positions`, `new_employment`, `continued_employment`, `change_employer` | int, null | non-integers → NULL, counted |
| `employer_name`, `trade_name_dba`, `employer_city`, `employer_state`, `employer_fein`, `naics_code`, `worksite_city`, `worksite_state` | text | as given; numeric-looking Excel cells lose a spurious `.0` (`541511.0` → `541511`) |
| `wage_rate_of_pay_from`, `wage_rate_of_pay_to`, `prevailing_wage` | numeric(14,2), null | `$` / `,` / spaces stripped; ranges, words or negatives → NULL, counted |
| `wage_unit_of_pay`, `pw_unit_of_pay` | text | `Hour` \| `Week` \| `Bi-Weekly` \| `Month` \| `Year`, as given |
| `pw_wage_level` | text, null | `I` \| `II` \| `III` \| `IV` \| `N/A`. Matters from FY2027: the H-1B cap lottery is weighted by OEWS level (IV = 4 entries … I = 1) |
| `fiscal_year` | int | federal FY of the file (Oct–Sep), given on the command line — not inferred from dates |
| `source_file` | text | basename of the file the row was last loaded from |
| `loaded_at` | timestamptz | when that load ran |
| `employer_key` | text, null | `normalize_company_name(employer_name)` — the same key as `companies.normalized_name`. Employer names are **not** deduplicated beyond that: "Amazon.com Services LLC" and "Amazon Web Services" stay separate employers |

**Personal data never loaded.** The files also carry real people's names, emails and phone numbers (`EMPLOYER_POC_*`, `AGENT_ATTORNEY_*`, `LAWFIRM_*`, `PREPARER_*`). The loader streams rows through an explicit 30-column allowlist (`COLUMN_MAP` in `src/visa/lca_loader.py`); every other cell is dropped as its row is read. Tested on synthetic files carrying invented values in those columns. Allowlisted columns missing from a file load as NULL with a warning; a file missing `CASE_NUMBER`, `CASE_STATUS` or `EMPLOYER_NAME` is refused.

### `v_employer_sponsorship` — employer-level sponsorship history

`sql/views/v_employer_sponsorship.sql`. One row per `(employer_key, period)`: `period = 'FY<year>'` per loaded fiscal year, plus `period = 'last_3_fy'` for the latest loaded FY and the two before it (`window_start_fy`..`window_end_fy`).

| Column | Meaning |
|---|---|
| `n_lcas_all_statuses` | every filing, any status or visa class (context only) |
| `certified_h1b_lcas` | `case_status = 'Certified' AND visa_class = 'H-1B'` |
| `certified_h1b_new_employment` | … of those, `new_employment > 0` |
| `certified_h1b_analytics_soc` | … of those, in the analytics SOC list |
| `certified_h1b_analytics_soc_new_employment` | both; drives the outlook's `strong` threshold |
| `wage_level_i` … `wage_level_iv`, `wage_level_na_or_missing` | wage-level mix of certified H-1B filings |
| `median_offered_annual_wage` | median of annualized `wage_rate_of_pay_from` over certified H-1B filings |
| `n_wage_unit_unconvertible` | certified H-1B filings whose unit isn't one of the five (annual wage NULL) |
| `latest_certified_decision_date` | most recent `decision_date` of a certified H-1B filing |
| `any_h1b_dependent`, `any_willful_violator` | any filing in the period flagged (any status / visa class) |

Judgment calls:
- **Certified-Withdrawn is excluded** from "certified": the employer withdrew it. Denied and Withdrawn are excluded. E-3 and H-1B1 are excluded — treaty visas an F-1 holder can't switch into.
- **The 3-FY window is data-relative** (anchored on `MAX(fiscal_year)` loaded), so the view is deterministic. It only reaches "now" once the newest FY's file is loaded. *(Parked.)*
- **Analytics SOC list** (default, *parked*), matched on the first 7 characters of `soc_code`: 15-2051 Data Scientists (incl. .01 Business Intelligence Analysts), 15-2041 Statisticians, 15-2031 Operations Research Analysts, 13-1161 Market Research Analysts, 15-1211 Computer Systems Analysts, 13-1111 Management Analysts, 15-1243 Database Architects, 13-2051 Financial and Investment Analysts. Lives in ONE place: the view's `analytics_soc` CTE.
- **Wage annualization**: Hour × 2080, Week × 52, Bi-Weekly × 26, Month × 12, Year × 1. Any other or missing unit → NULL and counted, never guessed. Uses the bottom of the offered range (`_from`); `_to` is often blank.

### Company ↔ LCA employer match review

`python -m src.visa.sponsor_match` writes `data/sponsor_match_candidates.csv` (`company_key, lca_employer_key, relation, similarity, approved`). Cross-set version of `find_merge_candidates`: same containment / fuzzy (`SequenceMatcher ≥ 0.88`) rule via the shared `classify_pair`, but each company key is compared only with LCA keys sharing its **first token** (blocking). So a typo in the first word is never proposed. The exact pair (company key = LCA key) is skipped because it already joins, but that company's longer variants in the same block ("fakeco holdings" for "fakeco") are still proposed. **Never auto-merged**: approved pairs are promoted by hand into `src/cleaning/data/company_aliases.json`, then `apply_cleaning --only companies` and `python -m src.visa.lca_loader --rekey` re-key both sides (no reload needed).

### `job_visa_signals` — what the posting itself says

One row per job (all jobs; the outlook view filters to in-scope), rebuilt wholesale by `python -m src.cleaning.apply_cleaning --only visa`. Pure classifier: `src/visa/posting_signals.py`; table-driven trap tests: `tests/test_posting_signals.py`.

| Column | Type | Meaning / judgment calls |
|---|---|---|
| `job_id` | int PK, FK → `jobs.id` | |
| `restriction` | text | `citizenship` \| `clearance` \| `none_found` |
| `restriction_reason` | text, null | the rule label and matched phrase, `usajobs KeyRequirements`, `ambiguous: <phrase>`, `negated: <phrase>`, or the Public Trust note |
| `sponsorship_stance` | text | `will_not_sponsor` \| `will_sponsor` \| `none_found` |
| `sponsorship_reason` | text, null | matched phrase, `ambiguous: <phrase>`, `ambiguous: conflicting …`, or the work-authorization note |
| `opt_mentioned` | bool | OPT / STEM OPT / CPT / "optional/curricular practical training" named. Independent of stance: "OPT/CPT welcome but no H-1B sponsorship" is `opt_mentioned = true` AND `will_not_sponsor` |
| `text_coverage` | text | `full` (description_full present) \| `truncated` (description only — Adzuna's ~500-char cap) \| `empty` |
| `cap_exempt_hint` | text | `likely` \| `unknown` |
| `cap_exempt_reason` | text, null | which name word matched, or which marker blocked it |
| `classified_at` | timestamptz | when the step ran (the only column that changes on an identical re-run) |

Judgment calls:
- **Input text** = title + `description_full`, else title + `description`. **`none_found` on truncated text means unknown, never "sponsors".**
- **"Authorized to work in the US" alone is NOT a restriction and NOT will_not_sponsor** — OPT is work authorization. It becomes `will_not_sponsor` only next to "without sponsorship", "now or in the future" or similar. Alone it is `none_found` with a reason saying so.
- **"U.S. person"** (export-control / ITAR wording) → `citizenship` with its own reason (`us_person …`): it excludes F-1 holders.
- **Clearances** (TS/SCI, "active Secret", "ability to obtain a clearance", "security clearance required") → `clearance`: a US clearance requires citizenship. Negated ("no security clearance required") → `none_found`, reason `negated: …`.
- **"Public Trust" is not a restriction** *(parked)*; the mention is recorded as the reason.
- **Citizenship needs a requirement verb** ("must be", "required", "only", "Who May Apply: US Citizens"). "U.S. citizenship preferred" and other unreadable mentions → `none_found`, reason `ambiguous: …`. EEO boilerplate ("without regard to … citizenship status") is ignored.
- **Uppercase `US` only**: lowercase "us" is a pronoun ("help us persuade…"). Lowercase "must be a us citizen" therefore lands as `ambiguous`, not `citizenship` — precision over recall.
- **Sponsorship words need visa context** for positives ("we sponsor H-1B", "visa sponsorship available"); "executive sponsor" and "we sponsor hackathons" are traps. A negated positive ("no visa sponsorship available") is a negative. A will-not AND a will in one posting → `none_found`, `ambiguous: conflicting …`. The application question "Will you now or in the future require sponsorship?" alone → `ambiguous`.
- **OPT/CPT are case-sensitive** ("opt in" is not OPT); "CPT codes" / "CPT/ICD" (medical billing) are traps.
- **USAJobs structured field beats text**: a `US Citizenship…` entry in the raw response's `UserArea.Details.KeyRequirements` (matched on `MatchedObjectId = external_id` in the job's `raw_response_id` page) → `citizenship`, reason `usajobs KeyRequirements`. When that field is absent or lists no citizenship entry, the text rules still run — it is filled in for only 1 of 25 fixture postings, while 10 of 25 state citizenship in the Requirements text.
- **`cap_exempt_hint = likely`** only when the company name contains University, College, Community College or Institute of Technology AND no for-profit marker (legal-entity suffixes Inc/LLC/Corp/Ltd/PLC/LP/LLP/Holdings, "Education Group", "Credit Union", "Bank", "Bookstore"). Hospitals, medical centers, health systems and labs → `unknown` with a "parked" reason. Research nonprofits and government labs without those words → `unknown`. A hint, never a determination: the LCA data has no cap-exempt field, and for-profit colleges (which are not exempt) don't always say so in their name.

### `v_job_visa_outlook` — one verdict per in-scope job

`sql/views/v_job_visa_outlook.sql`; read by `python -m src.visa.scan`. In-scope jobs ⟕ `job_visa_signals` ⟕ `v_employer_sponsorship` (`period = 'last_3_fy'`, on `companies.normalized_name = employer_key`). Carries the posting signals, the employer aggregates (0 when unmatched), `employer_matched`, `bucket` and `bucket_reason`.

Buckets, first match wins (thresholds *parked*):
1. `closed` — restriction is citizenship or clearance, or stance is `will_not_sponsor` (a "no" in the posting beats any history)
2. `strong` — `will_sponsor`, or ≥ 3 certified analytics-SOC H-1B LCAs with new employment in the last 3 FYs, or `cap_exempt_hint = likely`
3. `possible` — any certified H-1B LCA in the last 3 FYs
4. `unknown` — everything else, including no employer match and jobs the visa step hasn't classified yet

`unknown` is not "no", and `strong` is not "yes": see "What this can't tell you" in `src/visa/README.md`.

---

## Daily clock *(added with the daily runner)*

How the project proves ingestion runs every day. Operating guide: [`docs/daily-operation.md`](daily-operation.md).

### `ingestion_runs` — one row per ingestion run per source

Written by `src/ingestion/run_log.py`, used by both ingest CLIs and `python -m src.pipeline.daily`. A row is committed as `running` when the run starts and is **always** closed with a final status, including when the run raises. A row still `running` with no `finished_at` means the process was killed. Dry runs write no row.

| Column | Type | Meaning / judgment calls |
|---|---|---|
| `id` | serial PK | |
| `source` | text | `adzuna` \| `usajobs` |
| `started_at` | timestamptz | when the run opened its row |
| `finished_at` | timestamptz, null | NULL while running (or if the process died) |
| `status` | text | `running`, then one of `ok` (finished normally), `partial` (the per-run call cap cut it short: `CallBudgetExceeded`), `failed` (an exception: API/network error, or credentials missing before a client could be built), `skipped_budget` (the monthly guard's cap was ≤ 0, so no call was made) |
| `calls_made` | int | the client's `calls_made`: **every HTTP attempt, retries and failures included**. This is what the monthly budget bills against |
| `pages_fetched` | int | pages persisted (successful, non-empty) |
| `jobs_processed` | int | job rows upserted (counted once per page appearance, so it can exceed distinct jobs) |
| `jobs_new` | int | jobs for the source after the run minus before it. Ingestion is single-writer (advisory lock), so this is the run's inserts |
| `snapshot_date` | date, null | the UTC date at run start: the date its snapshots land on (a run straddling UTC midnight can write both dates) |
| `params` | jsonb | what was asked for: `queries`, `series_codes` (USAJobs), `max_pages`, `max_calls` (the cap actually used), `requested_max_calls` (Adzuna, before the guard), `dry_run`. **Never credentials** |
| `error` | text, null | why it failed or was skipped. Passed through `redact()` (Settings credentials and any `app_id=`/`app_key=` query value become `***`) and capped at 2,000 characters. Missing-credential errors name the variable, never a value |

Index: `(source, started_at)`.

**Redaction**: a `requests` network error's message contains the full URL, and Adzuna puts `app_id`/`app_key` in the query string. Both clients mask that text before logging or raising it, and the CLIs and the daily runner install `RedactingFilter` (`src/utils/redaction.py`) on their log handlers. USAJobs' key and user-agent email are treated as secrets too.

### Monthly Adzuna budget (`src/ingestion/budget.py`)

```
used = max(SUM(ingestion_runs.calls_made) WHERE source='adzuna' AND started_at in this UTC month,
           COUNT(raw_responses)          WHERE source='adzuna' AND fetched_at in this UTC month)
cap  = min(--max-calls, (ADZUNA_MONTHLY_CALL_BUDGET - used - ADZUNA_MONTHLY_RESERVE) // days_left)
```

Judgment calls:
- The billing month is the **UTC calendar month** (parked; Adzuna may count differently).
- The larger of the two counts is used: raw_responses undercounts (successes only) but covers history from before the run log.
- The reserve defaults to 25, for manual and smoke-test calls.
- `days_left` includes today.
- If the cap is ≤ 0, the guard builds no client and records `skipped_budget`, which is not an error.
- An Adzuna dry run (`ingest_adzuna --dry-run`) still makes real calls, so it is capped too, but it records no row. Its calls are invisible to the guard except through the reserve.

### `v_ingestion_daily`

`sql/views/v_ingestion_daily.sql`. One row per (UTC `snapshot_date`, `source`), **built on `job_snapshots`** (joined to `jobs` for the source), so days from before the run log still appear. A missed day is a gap, not a zero row.

| Column | Meaning |
|---|---|
| `snapshot_rows` | job_snapshots rows that day (equal to `distinct_jobs` by construction, since the PK is `(job_id, snapshot_date)`) |
| `distinct_jobs` | distinct jobs observed that day |
| `new_jobs` | jobs whose `first_seen_at` (UTC) is that date |
| `n_runs`, `n_ok_runs` | ingestion_runs rows for that `snapshot_date` and source (0 before the run log) |
| `calls_made`, `jobs_processed` | summed over those runs; **NULL** when no run row exists (unknown, not zero) |

### Health thresholds (`src/pipeline/health.py`)

| Check | Rule | Default (parked) |
|---|---|---|
| H1 run freshness, per source | latest `ok`/`partial` `finished_at` within N hours, else FAIL. No run rows for the source at all: WARN "no run log yet" | 26 h (a daily run plus slack for a late wake) |
| H2 snapshot freshness | latest `snapshot_date` = today PASS, yesterday WARN, else FAIL | UTC dates |
| H3 snapshot volume, per source | WARN if the latest day's distinct jobs fell more than X against the previous snapshot day | 50% |
| H4 Adzuna budget | WARN at ≥ X of the month used, FAIL at ≥ 100% | 85% |
| H5 cleaning freshness | WARN if any job has no `job_visa_signals` row | — |
| H6 failed runs | WARN if any run in the last N days ended `failed` | 7 days |
| Progress (INFO) | unique jobs / 10,000; distinct snapshot days / 90; current streak (consecutive snapshot days ending today or yesterday) / 60; first snapshot date | targets from the project guide |

The exit code is 1 only on a FAIL. A month with only `skipped_budget` Adzuna runs FAILs H1 for Adzuna after 26 hours, which is intended: no Adzuna data is arriving. H4 says why.
