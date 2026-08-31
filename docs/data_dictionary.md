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
