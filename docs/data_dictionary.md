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
| `salary_min`, `salary_max` | int, null | `NULL` = not disclosed. **Never zero-filled.** |
| `salary_currency` | text, null | `'USD'` when salary present (US endpoint); `NULL` otherwise |
| `salary_period` | text, null | `'year'` when salary present — Adzuna US returns annualized figures. **Caveat**: suspected hourly-as-annual contamination in the low tail (see phase 1 findings); Phase 2 adds a quality flag. |
| `salary_is_predicted` | bool, null | `true` = the figure is **Adzuna's model estimate**, not employer-disclosed. Must be separable in every salary analysis. |
| `is_remote` | bool | Phase 1 signal = word-boundary `remote` in title or location display name. **A floor, not an estimate** — description-level detection is Phase 2. |
| `category` | text, null | Adzuna category label, e.g. `'IT Jobs'` |
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
