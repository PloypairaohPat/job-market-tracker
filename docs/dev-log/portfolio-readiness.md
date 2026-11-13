# Portfolio readiness: final report

Phase 1 of the portfolio-readiness brief (Parts A to G). This file replaces
the working progress file, whose contents are folded in below.

## Report

- **Branch:** `claude/portfolio-readiness`, from main at **2f80d85** (main has not moved since).
- **Commits pushed:** 20 (A1 to F2, plus this report).
- **How far:** Parts **A, B, C, D, E and F are complete.** Part G (stretch) is
  **not started**; it becomes the first item of the next phase (see below).
- **STOP conditions** (checked on the first run): 2f80d85 is in main's
  history; the baseline was green; `alembic heads` showed one head
  (a02471448340); main had no `docs/reports/`, no `--publish`, no
  `src/shortlist*`, and no remote `claude/portfolio-readiness`.
- **Compare:** https://github.com/PloypairaohPat/job-market-tracker/compare/main...claude/portfolio-readiness?expand=1

### Verification

| Check | Baseline (main 2f80d85) | Final (this branch) |
|---|---|---|
| pytest (TEST_DATABASE_URL set, fresh `jobmarket_test`) | 705 passed, 1 skipped | **835 passed, 1 skipped** (the skip is the Metabase end-to-end test, needs METABASE_URL) |
| `ruff check .` / `ruff format --check .` (0.17.2) | clean | clean |
| `alembic upgrade head && downgrade base && upgrade head` on a fresh database | clean | clean; still one head, a02471448340; no new migration |
| `make views` twice on a fresh alembic-built database | 22 views | **25 views** (+ `v_search_window_coverage`, `v_job_observation_spans`, `v_daily_market_flow`) |
| Pipeline image (`docker build`, `scripts/verify_image.sh`) | 985MB, Jupyter inside | 675MB, no Jupyter; verify OK (C5) |
| CI on the branch (GitHub Actions) | n/a | green on every pushed commit through E4; the F commit's run was in progress when this report was written |

Acceptance-criteria spot checks on the final head:
`git grep -n -i -E "spacy|prefect" docs/PROJECT_GUIDE.md` matches only
three lines, each saying planned, deferred or not used;
`git grep -n "docs/overnight-"` and `git grep -n YOUR_USERNAME README.md`
match nothing; the added lines of `git diff main` contain no `@gmail` and no
`C:\Users\<name>`; `git diff main --name-only` lists no `data/`, `logs/`,
`.env`, `uv.lock`, `company_aliases.json`, `narrative.md` or
`docs/reports/` file. LICENSE exists.

## What shipped

| Part | Commit | What |
|---|---|---|
| A1 | e5673a6 | One engine and sessionmaker per database URL; `dispose_engines()` |
| A2 | 92e4617 | The skills step converges: stale links deleted, docstring fixed |
| A3 | 1841143 | Remote detection reads `description_full`; federal ad-hoc telework is a negation |
| B1-B4 | 3936168 | `--init-narrative`, `--publish`, `--index`, the README published-reports block, docs |
| C4 | 6ef0f28 | Work logs moved to `docs/dev-log/` with a README |
| C5 | e064fbb | Jupyter moved to the `notebook` extra; the image check enforces it |
| C2 | 4f3a15a | MIT LICENSE (holder to confirm, Q5) |
| C1 | da62780 | README restructured: findings, reports, dashboards, status table |
| C3 | ad71ea3 | PROJECT_GUIDE truth pass |
| D1 | 55384bb | `v_search_window_coverage` |
| D2 | 545aa30 | Optional `ADZUNA_SORT_BY`; `--sort-by` on the smoke script |
| D3, D4 | f0fb971 | `v_job_observation_spans`, `v_daily_market_flow`; `removed_at` documented as reserved |
| D5 | a7c8fb4 | `docs/time-series-readiness.md` |
| D6 | 129bb0d | Doctor check 11: search-window coverage |
| E0 | 4a794cb | Frozen reference code, reference-equality test, `scripts/bench_cleaning.py` |
| E1 | e80eab5 | One batched pass over `jobs` for seniority, salary, remote, scope |
| E2 | 26f9834 | Visa signals in bulk; raw pages read once per batch |
| E3 | 865b9a5 | Skills: keyset paging, one upsert and one delete per batch |
| E4 | 15eb037 | Statement-count test; before/after timings |
| F1, F2 | c5eaf2d | `python -m src.shortlist`, example profile, tests, `docs/shortlist.md` |

Details per part are in each commit message and in the evidence below.
Changed test expectations (old and new) are recorded under A3, B and D6
in the evidence.

### Part G and the next phase

Not started in Phase 1. G1 (`v_analysis_population`), G2 (wake-to-run:
63ea064 on `claude/battery-fix` is **not** in main, so
`scripts/windows/register_daily_task.ps1` was not touched) and G3 (a demo
dashboard screenshot) are the first items of the follow-up branch
`claude/portfolio-next`.

## Parked questions

| Q | Part | Question | Recommendation (built as the default) |
|---|---|---|---|
| Q1 | A2 | Should `sync_taxonomy` delete `skills` rows that left the taxonomy? | No: keep the row, log how many are orphaned |
| Q2 | A3 | Should federal remote become a reported rate once a sample is checked on real data? | No change now; Report 2 keeps "not measurable" |
| Q3 | B | Should `--publish` refuse when `sql/views/` or `src/reports/` has uncommitted changes? | Warn, don't refuse |
| Q4 | B | Export published reports as HTML or PDF too? | Not now; Markdown renders on GitHub |
| Q5 | C2 | Licence and holder: MIT / Apache-2.0 / none; holder "Pat Ploypairaoh" | MIT, 2026, Pat Ploypairaoh; confirm before merging |
| Q6 | D2 | Turn on `ADZUNA_SORT_BY`? | Decide after looking at `v_search_window_coverage` on real data; the earlier the better |
| Q7 | D4 | `jobs.removed_at`: (a) leave unset and documented, (b) set after N unseen days, (c) drop later | (a) |
| Q8 | D6 | Doctor check 11's WARN threshold | 50% (`WINDOW_WARN_PCT` in `src/doctor.py`) |
| Q9 | F | With `metros` empty, should `include_remote = false` drop remote postings? | Yes (built): the option means the same thing either way |
| Q10 | C | A "How this was built" note in the README? | Not added; candidate wordings below |
| Q11 | E | Incremental cleaning of changed jobs only? | No: keep the full recompute so a rule change reaches every row |

**Q1.** *What I found:* `sync_taxonomy` only upserts; after A2, links to a removed skill are deleted, so an orphaned `skills` row is harmless and keeps old ids stable. *Options:* (a) keep and log [built]; (b) delete orphaned rows with no links; (c) add an `active` flag (needs a migration). *Recommendation:* (a).

**Q2.** *What I found:* 0 of 25 fixture postings flip to remote; federal telework text is mostly ad hoc or situational. *Options:* (a) keep "not measurable" [built]; (b) report a federal rate after a hand-checked sample. *Recommendation:* (a) until a real-data sample is checked.

**Q3.** *What I found:* a publish from uncommitted view or report code produces numbers no commit can reproduce. *Options:* (a) warn [built]; (b) refuse; (c) ignore. *Recommendation:* (a).

**Q4.** *Options:* (a) Markdown only [built]; (b) add HTML; (c) add PDF (would need a new dependency). *Recommendation:* (a) now, (b) later if a reader asks.

**Q5.** *What I found:* no LICENSE on main; the merge commits carry the name "Pat Ploypairaoh". *Options:* (a) MIT [built]; (b) Apache-2.0; (c) none (all rights reserved). *Recommendation:* (a), after confirming the name.

**Q6.** *What I found:* searches pass no sort order and stop at 250 results per query; how much that misses is unknown until D1's view runs on real data. *Options:* (a) leave unset; (b) set a date sort after one smoke call. *Recommendation:* look at coverage first; if shares are low, set it early and record the date.

**Q7.** *Options:* (a) reserved, documented [built]; (b) set after N unseen snapshot days; (c) drop in a later migration. *Recommendation:* (a): leaving the search window is not evidence of removal.

**Q8.** *Options:* (a) 50% [built]; (b) a different share; (c) INFO only. *Recommendation:* (a) until real coverage is seen.

**Q9.** *Options:* (a) drop remote postings when `include_remote = false` and no metros are set [built]; (b) no effect without metros. *Recommendation:* (a).

**Q10.** *What I found:* main's history has 80 commits authored "Claude", 18 "Developer" and 9 "Pat Ploypairaoh"; the briefs and session logs are in `docs/dev-log/`. Candidate wordings, for the owner to choose, edit or drop:
1. "Much of the code was written in AI-assisted sessions from written briefs; the briefs' outcomes and the decisions they left open are logged in `docs/dev-log/`."
2. "Built with AI coding assistance. Commit authorship shows which commits came from assisted sessions; `docs/dev-log/` holds their work logs."
3. "Development used an AI coding assistant working from written briefs (logs in `docs/dev-log/`); product decisions, analysis and narrative are the owner's."
(The third makes a claim about the owner's role that only the owner can confirm.)

**Q11.** *Options:* (a) full recompute [built]; (b) incremental, guarded by the E0 reference-equality test. *Recommendation:* (a): after Part E a full pass over 20,000 synthetic jobs takes under 20 seconds excluding the company step.

### C6: the lock file

`uv.lock` stays untracked on this branch. Recommendation: commit it from the
laptop. The README tells readers to run `uv sync`; with the lock file in the
repo, that command installs exactly the versions the owner tested, on any
machine and in CI, instead of whatever is newest that day. Without it, a
clone months from now can pull a newer pandas, SQLAlchemy or matplotlib
and fail, or render charts slightly differently, with nothing in the repo
recording what last worked.

## What only the owner can do, in order

Windows PowerShell, from the repo root.

1. **Merge.** Check CI on `claude/battery-fix` and merge it if green; then open and merge this branch's PR. Then:
   ```
   git checkout main
   git pull
   uv sync
   uv run alembic upgrade head
   uv run python scripts/apply_views.py
   uv run python -m src.doctor
   ```
   Expect "25 views applied" for this branch alone, or "26 views applied" once `claude/portfolio-next` is merged too (it adds `v_analysis_population`). The doctor now has 11 checks; check 11 may WARN (see step 3).
2. **Git identity** for the owner's own commits (use the GitHub noreply address from github.com/settings/emails):
   ```
   git config user.name "Pat Ploypairaoh"
   git config user.email "<id>+<username>@users.noreply.github.com"
   ```
3. **Search-window coverage on real data**, in psql or a Metabase native query:
   ```
   select * from v_search_window_coverage order by fetch_date desc, source, query;
   ```
   A share well below 100% means each day's snapshot holds only the first slice of that query's results, so a job missing from a day may have left the window rather than the market. Then decide `ADZUNA_SORT_BY` (Q6). Confirm the accepted values in Adzuna's documentation and make one call first:
   ```
   uv run python scripts/smoke_adzuna.py --sort-by date
   ```
4. **The snapshot checks** in `docs/time-series-readiness.md` ("Checks to run on real data before trusting any trend"), on the snapshot days that exist.
5. **Write Report 3 first**:
   ```
   uv run python -m src.reports employers-and-sponsorship
   uv run python -m src.reports employers-and-sponsorship --init-narrative
   notepad "docs\reports\employers-and-sponsorship\narrative.md"
   uv run python -m src.reports employers-and-sponsorship --publish
   ```
   Read every stale-number warning, fix the narrative, publish again, then:
   ```
   git add "docs/reports/employers-and-sponsorship" README.md
   git commit -m "Publish Report 3"
   ```
   Then the other three the same way.
6. **Replace the README's findings bullets** with current figures from the published reports, in your own words.
7. **The server cut-over** (`docs/deploy.md`), then the public dashboard links and a real screenshot.
8. **Decide** the LICENSE (Q5), committing `uv.lock` (C6) and the "How this was built" note (Q10).
9. **The shortlist**:
   ```
   Copy-Item "shortlist.example.toml" "shortlist.toml"
   notepad "shortlist.toml"
   uv run python -m src.shortlist
   ```
10. **Replace the copy of `docs/PROJECT_GUIDE.md`** in the Claude project with the corrected one, and practise the pitch against it.

## Samples on demo data

<details>
<summary><b>SYNTHETIC</b>: <code>--publish</code> sample, Report 2 on the demo database (test-only override), invented narrative text</summary>

```markdown
<!-- Published by `python -m src.reports how-much-employers-disclose --publish`. Tables, charts and numbers are recomputed from the SQL views; the narrative sections come from docs/reports/how-much-employers-disclose/narrative.md. Edit that file and publish again rather than editing this one. -->

> **Synthetic demo data, not market findings.**

# How much employers disclose

_Phase 5 report 2. Regenerates Phase 3 Investigation #3 (docs/phase_3_findings.md) from the SQL views._

| Provenance | |
|---|---|
| Database | `jobmarket_demo` |
| Generated at | 2026-11-13 01:10:31 UTC |
| Git commit | `c5eaf2d5efe7` |
| Rows in `v_field_completeness` | 2 |
| Rows in `v_field_completeness_counts` | 2 |

## Headline

Invented placeholder text for a synthetic sample.

## 1. Who is compared

**Commercial** is every Adzuna posting; **federal** is every USAJobs posting classified in scope (`jobs.in_scope`). Every figure is per market. A blended "% populated" would be a category error: federal pay bands are disclosed by law, commercial salaries by choice.

| Market | Jobs |
|---|---|
| commercial | 609 |
| federal | 5 |

[... sections 2 onward as in a normal render, each narrative placeholder replaced by the invented text; no 'numbers from this run' lists ...]
```

Published through `publish(..., allow_demo=True)` into a scratch directory;
the CLI has no such option. Nothing was written under `docs/reports/`.
</details>

<details>
<summary><b>SYNTHETIC</b>: shortlist sample on the demo database with the example profile</summary>

The demo dataset reuses employer names from the test fixtures; the employer
is replaced here so no name appears next to a visa bucket.

```markdown
# Shortlist, 2026-11-13

Private: this file names postings and employers. Never commit it.

**Synthetic demo data, not real postings.**

Generated 2026-11-13 01:06 UTC from `127.0.0.1/jobmarket_demo`: postings first seen in the last 7 day(s) that pass the profile, reposts collapsed into one entry per employer and title, newest first.

> Commercial (Adzuna) descriptions are truncated by the API, so a skill missing from a commercial posting may simply have been cut off; skill filters can drop commercial postings that do ask for the skill.

69 entries.

## Product Analyst, [employer]

- Where: location not given
- Link: https://www.adzuna.com/land/ad/5000000075
- Salary: $75,000–$85,000 a year (employer-disclosed)
- Skills matched: Looker, SQL
- Visa outlook: unknown
- Seniority: no title signal
- First seen 2026-11-13 on adzuna; 3 postings
```
</details>

## Surprises

- The demo seed stores synthetic raw responses whose invented totals exceed the window, so doctor check 11 WARNs on the demo database by design (the end-to-end doctor test expects it).
- The E0 equality test first passed a deliberate regression (reverting A3's full-text read): no seeded row had a remote phrase only in `description_full`. An edge row was added, and the test now fails on that regression.
- The bench's statement counter has to count psycopg2 `executemany` once per row, but SQLAlchemy's batched "insertmanyvalues" INSERT once per statement; counting naively made the old code look cheap.
- At 20,000 synthetic jobs the `companies` step (pairwise fuzzy merge candidates) takes ~22 s, now the slowest step. Part E didn't cover it.
- Docker Hub returned HTTP 429 for the base image during C5; the image was pulled from mirror.gcr.io and retagged, with the Dockerfile unchanged.

## Suggested PR

**Title:** Portfolio readiness: three correctness fixes, a publish path for reports, docs that match the code, snapshot views, faster cleaning, a private shortlist

<details>
<summary>PR description</summary>

```markdown
## Summary

Works through the portfolio-readiness brief, Parts A to F. No migration, no new runtime dependency, no change to any existing view's output; synthetic data only. Full report: docs/dev-log/portfolio-readiness.md.

### A: correctness
- A1: one engine and connection pool per database URL (was one per `session_scope(url)` call).
- A2: the daily skills step converges: links that no longer match are deleted.
- A3: remote detection reads `description_full` when present; federal ad-hoc/situational telework counts as not remote. Commercial results unchanged (tested).

### B: a publish path for the reports
- `python -m src.reports <slug> --init-narrative` and `--publish`; narrative lives in `docs/reports/<slug>/narrative.md`.
- Refuses demo/test databases, missing or placeholder sections, guardrail failures, and employer names in Report 3's sponsorship sections; warns on stale figures.
- README block listing published reports (`--index`).

### C: docs match the code
- README restructured; PROJECT_GUIDE claims that the repo doesn't back removed or rewritten; work logs moved to docs/dev-log/; MIT LICENSE (to confirm); Jupyter out of the pipeline image (985MB -> 675MB).

### D: snapshot data
- New views: `v_search_window_coverage`, `v_job_observation_spans`, `v_daily_market_flow`.
- Optional `ADZUNA_SORT_BY` (unset = identical requests); `removed_at` documented as reserved; docs/time-series-readiness.md; doctor check 11.

### E: cleaning efficiency
- Job-level steps in one batched pass; visa signals and skills in bulk; results pinned by a reference-equality test. 20,000 synthetic jobs: 41.9 s -> 16.8 s excluding the unchanged company step.

### F: a private shortlist
- `python -m src.shortlist` from a gitignored `shortlist.toml`; output under data/shortlist/, never committed.

## Checks
- pytest: 705 passed, 1 skipped -> 835 passed, 1 skipped
- ruff 0.17.2 clean; alembic round trip clean, one head; `make views` twice: 25 views

## Owner decisions parked
Q1-Q11 in the report (licence holder, sort order, thresholds, and others).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01LEYQv8Tjr7ztYstzdG71MZ
```
</details>

## Evidence

### A3 fixture evaluation (`tests/fixtures/usajobs_sample_response.json`, 25 postings)

- Postings that flip to remote when `description_full` is read: **0 of 25**.
- No `_POSITIVE` pattern matches any fixture `description_full`. Telework
  phrases present: "Telework: Ad Hoc" (882530900), "Telework: Ad hoc per
  agency policy" (882742600), "Telework: This position may be authorized
  for telework" and "Telework eligibility will be discussed during the
  interview process" (882748500). None contains a positive pattern.
- Tightened anyway, because the full text now reaches the classifier:
  "situational / ad hoc / ad-hoc / episodic / occasional" followed by
  telework or telecommuting, and "Telework: Ad hoc" / "Telework:
  Situational", are NEGATION patterns. Each phrase is tested in
  `tests/test_remote_full_text.py`. Side effect: a commercial description
  containing one of those phrases plus a positive phrase now comes out
  not remote (consistent with the stated policy; no fixture or demo row
  is affected).
- Changed test expectation: the Report 2 golden file
  (`tests/fixtures/reports/how-much-employers-disclose.md`) row "Remote"
  reason text. Old: "the classifier scans `jobs.description` only ...".
  New: "the classifier reads `description_full` when present ... federal
  is not measurable". No number changed.

### B: changed test expectations

- All four golden files (`tests/fixtures/reports/*.md`), line 1 only. Old:
  "... and the file is overwritten: write narrative in a copy
  (docs/reports.md)." New: "... write the narrative in
  docs/reports/<slug>/narrative.md and publish (docs/reports.md)."
- Each report module now declares `SECTIONS` (heading -> purpose) and its
  placeholders read from it; the goldens prove the rendered text is
  otherwise unchanged.
- Report 3's narrative rule is built (not parked): `employers.check_published`
  refuses a narrative paragraph that uses sponsorship vocabulary (sponsor,
  LCA, H-1B, visa, filing, filed, certified, outlook) and names an employer
  from the top-employers tables, and re-runs `check_sponsorship_text` and
  `check_caveats` over the merged text.

### C5: image check

Built locally with Docker (base image pulled from mirror.gcr.io because
Docker Hub returned 429, then tagged with the Dockerfile's name; the
Dockerfile is unchanged).

| Image | Disk usage | Content size | Jupyter inside | `scripts/verify_image.sh` |
|---|---|---|---|---|
| before (main's pyproject) | 985MB | 212MB | jupyter, notebook, jupyterlab, ipykernel | OK before the new check; FAIL with it |
| after (`notebook` extra) | 675MB | 148MB | none | OK |

`verify_image.sh` now fails if any of jupyter, notebook, jupyterlab or
ipykernel is importable in the image.

### C1: README figure-to-source table

All three bullets quote `docs/phase_3_findings.md`, whose last commit on
main is 34ad172 (2026-09-03): the "as of" date. Each figure is one the
doc presents as its key result and clears the doc's own floors (salary
n >= 15; composition shares come with counts). None is marked
"directional only".

| README figure | Source line | Population and n as stated there |
|---|---|---|
| median $98,500, IQR $87,013–$111,425, n=178 | `docs/phase_3_findings.md:39` | commercial, `salary_quality='ok'`, USD, year, `salary_is_predicted=false` |
| 12.1% (180) commercial, 100.0% (70) federal employer-disclosed salary | `docs/phase_3_findings.md:268` | commercial n=1,483; federal in-scope n=70 (header line 265) |
| workflow + bi_tool 56.7% combined; ml_stats + language 67.0% combined | `docs/phase_3_findings.md:184-185` (table header line 174: n=1,483 / n=70 jobs, confidence >= 0.8) | share of each market's own skill tags |

Moved out of the README (not duplicated): the laptop-vs-server table and
"exactly one machine ingests" to `docs/deploy.md`; the ingestion CLI
flags to `docs/daily-operation.md`; dashboard commands were already in
`docs/dashboard.md`. The status paragraph and roadmap became the Status
table. "In three minutes" lost only the dashboard list that the
Dashboards section now carries; the owner's other sentences are kept
as written.

### C3: PROJECT_GUIDE claims removed or changed

| Claim (before) | Change | Why |
|---|---|---|
| 30-second pitch: insights "about which skills carry salary premiums, how demand shifts over time, and where the strongest hiring markets are"; "runs a daily ingestion job ... presents the analysis through a Metabase dashboard and a series of written reports" | Replaced by a list of checkable facts with file paths | The premium was deferred; no time-series or metro-demand finding exists; reports have no narrative yet |
| Two-minute pitch: "extracts skills ... using spaCy"; "Jupyter investigations"; "skill-salary correlations, geographic demand patterns, and how the market shifts over time"; "runs on a Hetzner VPS with Prefect for orchestration" | Replaced by facts list | Extraction is a regex taxonomy; investigations are SQL views + findings docs; deploy kit unused; no Prefect |
| Tech stack: NLP = spaCy; Orchestration = Prefect; Deployment = Hetzner VPS; Visualization = Plotly + matplotlib | Table rewritten to what exists, with file paths | spaCy/Prefect not used; deploy kit unused; Plotly is a dependency no code imports |
| "Why Python": "pandas, spaCy, scikit-learn, and Jupyter" | spaCy dropped from the sentence | not used |
| Data sources: Greenhouse/Lever "Optional (Phase 3+)" | Marked "Planned, not built" | not built |
| Target roles include "Data Scientist (for comparison)" | Replaced by the six real `TARGET_QUERIES` and a note | Data Scientist is not queried |
| Target geographies "..., Austin, Remote" | Replaced by the real metro list (adds DC; remote is a flag) | matches `src/cleaning/metro.py` |
| Architecture diagram: "Python + Prefect", "pandas + spaCy", Greenhouse/Lever source | Replaced by a numbered description pointing to the README diagram | diagram described unbuilt parts |
| "This pattern is borrowed directly from my finance dashboard project where it proved invaluable." | Removed | an anecdote no file in the repo backs; restore if true |
| Database schema (v1) listing (`job_snapshots` with `id SERIAL` and a composite key, `skills.category` values 'tool'/'soft', no `description_full`, `in_scope`, visa or run-log tables) | Replaced by a table of the real tables, pointing to `docs/data_dictionary.md` | listing no longer matched the models |
| Phased roadmap with week estimates, "spaCy-based skill extraction", "Jupyter notebook portfolio ... Each notebook is publication-quality", "Prefect orchestration, ... public deployment to Hetzner" | Replaced by a phase/status table; the plans moved to "Planned, not built" | not built |
| Skills demonstrated: "NLP: spaCy", "Orchestration: Prefect", "Production deployment: ... self-hosted on Hetzner VPS", "Statistical analysis: ... correlation, cohort analysis, basic clustering", "Plotly" | Rewritten, each bullet with the file that shows it | none of these exists |
| Talking point "hardest part": the Meta / Facebook / FB normalization story, regional subsidiaries, recruiting agencies, "hybrid approach ... raw_names array" | Replaced by documented candidates with file paths | the story can't be traced to a file; the real approach (normalized_name + fuzzy candidates for manual review) is listed |
| "Messy data" answer in first person | Turned into fact bullets with paths | answers are the owner's to write |
| "What insights": "SQL + Python + Tableau ... about a [X]% salary premium" | Removed; points to README findings and published reports | no such finding; premium deferred |
| "What would you do differently": taxonomy rework in Phase 3; "an upstream ingestion bug that had been silently double-counting some postings" | Removed; points to parked decisions and open threads | no file records either story |
| "How does this scale" answer (DuckDB/ClickHouse, partitioning) | Replaced by facts to start from | first-person answer; nothing in the repo backs the plan |
| "What did you learn": "30% / 70%" judgment answer | Replaced by pointers to findings docs | first-person answer, and the split is not measured anywhere |
| Glossary entries for Prefect and spaCy | Removed; LCA added | not used; LCA is |
| Risks: "add spaCy patterns iteratively" | Says spaCy was planned and deferred | not built |

Kept as written (the owner's own motivation, not claims about the repo):
"Why this project exists", the Python and Metabase rationale, "Why not
LinkedIn / Indeed", the risks table (one cell changed) and the success
metrics checklist.

### D6: changed test expectations

`tests/test_doctor.py`: the doctor now has 11 checks. Old: check ids
`list(range(1, 11))`; new: `list(range(1, 12))` (CLI JSON test and the
unreachable-database test, which also expects check 11 to SKIP). The
demo-seed end-to-end test expects check 11 = WARN: the demo seed's
synthetic searches store 100 results of a larger invented total. The
exit code there stays 0.

### E0: reference and benchmark

- `tests/reference_cleaning.py`: a copy of the job-level steps, metro,
  visa and `extract_for_all_jobs` as they stood after D (post-A2/A3, so no
  intended difference; only the stale-link log line dropped).
- `tests/test_cleaning_reference_equality.py`: both sides start from the
  same scrambled state (demo seed + six invented edge rows + a skill that
  left the taxonomy), and must leave identical contents and counts, at
  `min_confidence` 0.0 and 0.8; plus a second-run-changes-nothing test.
  Checked that it catches a regression: reverting A3's full-text read in
  production makes it fail.
- `scripts/bench_cleaning.py`, before Part E (this VM, Postgres 16 local;
  "st" = SQL round trips, an executemany counted once per row):

```
step                      N=5000               N=20000
seniority       0.35s     2505 st      1.50s     9953 st
salary          0.43s     3969 st      1.96s    15951 st
remote          0.23s     1202 st      1.09s     4836 st
metro           0.00s        9 st      0.00s        9 st
companies       1.38s      502 st     21.73s     2002 st
scope           0.53s     5001 st      2.40s    20001 st
visa            1.02s       85 st      4.34s      334 st
skills          8.05s    23439 st     30.59s    92639 st
total          11.99s                 63.61s
```

Surprise: at 20,000 jobs (2,000 invented companies) the
`companies` step is the second-slowest: `find_merge_candidates` compares
every pair of names. Part E doesn't cover it; not changed.

### E4: after Part E (same machine, same script)

```
step                      N=5000               N=20000
seniority       0.13s        7 st      0.59s       21 st
salary          0.18s        7 st      0.73s       21 st
remote          0.10s        7 st      0.42s       21 st
metro           0.01s        9 st      0.00s        9 st
companies       1.29s      502 st     22.88s     2002 st
scope           0.31s        7 st      1.19s       21 st
visa            0.77s       13 st      3.06s       42 st
skills          2.74s      103 st     10.78s      193 st
total           5.53s                 39.65s            
```

Excluding `companies` (unchanged by Part E): 10.61s -> 4.24s at 5,000
jobs, 41.88s -> 16.77s at 20,000. SQL round trips against all tables
for the job-level steps: from one per job to a few per 2,000-job batch.

`tests/test_cleaning_bulk.py::test_statements_against_jobs_are_a_small_constant`
seeds 40 and 400 jobs (both inside one batch of every step) and asserts
identical per-step counts of statements touching `jobs`, each at most 3
(seen: seniority/salary/remote/scope 3 = read, UPDATE, final empty read;
visa 2; skills 2; companies 1; metro 0). Beyond one batch the count grows
by one read and at most one write per batch (2,000 jobs for the job-level
steps and visa, 500 for skills), not per job. No wall-clock assertion.
