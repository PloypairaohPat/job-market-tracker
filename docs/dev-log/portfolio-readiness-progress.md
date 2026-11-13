# Portfolio readiness: progress

Working file for the portfolio-readiness brief (Parts A to G). Folded
into `docs/dev-log/portfolio-readiness.md` when Parts A to F are done.

- Branch: `claude/portfolio-readiness`, from main at 2f80d85.
- Baseline (clean main, TEST_DATABASE_URL set): **705 passed, 1 skipped**.
- STOP conditions checked on the first run: 2f80d85 is in main; baseline
  green; one alembic head (a02471448340); no `docs/reports/`, no
  `--publish`, no `src/shortlist*`, no remote `claude/portfolio-readiness`.

## Parts

| Part | Status | Commits |
|---|---|---|
| A1 one engine per URL | done | A1 |
| A2 skills step converges | done | A2 |
| A3 remote reads full text | done | A3 |
| B1-B4 narrative files, publish, README block, docs | done | B1-B4 |
| C4 work logs moved to docs/dev-log/ | done | C4 |
| C5 Jupyter out of the pipeline image | done | C5 |
| C2 MIT LICENSE | done | C2 |
| C1 README restructure | done | C1 |
| C3 PROJECT_GUIDE truth pass | done | C3 |
| C6 lock file (report only) | in the final report | - |
| D1 v_search_window_coverage | done | D1 |
| D2 optional ADZUNA_SORT_BY | done | D2 |
| D3 v_job_observation_spans, v_daily_market_flow | done | D3 |
| D4 removed_at documented as reserved | done | D3 (same commit) |
| D5 docs/time-series-readiness.md | done | D5 |
| D6 doctor check 11, search window | done | D6 |

## Latest test count

795 passed, 1 skipped (after D6).

## Parked questions

| Q | Part | Question | Default built |
|---|---|---|---|
| Q1 | A2 | Should `sync_taxonomy` delete `skills` rows that left the taxonomy? | No: keep the row, log how many are orphaned |
| Q2 | A3 | Should federal remote become a reported rate once the owner has checked a sample on real data? | No change now; Report 2 keeps "not measurable" |
| Q3 | B | Should `--publish` refuse when `sql/views/` or `src/reports/` has uncommitted changes? | Warn, don't refuse |
| Q4 | B | Should published reports also be exported as HTML or PDF? | Not built; Markdown only |
| Q6 | D2 | Turn on `ADZUNA_SORT_BY`? | Owner decides after looking at `v_search_window_coverage` on real data; the earlier the better |
| Q7 | D4 | `jobs.removed_at`: (a) leave unset and documented, (b) set after N unseen snapshot days, (c) drop in a later migration | (a), built |
| Q8 | D6 | Threshold for doctor check 11's WARN (any query's captured share on the latest day) | 50% (`WINDOW_WARN_PCT` in `src/doctor.py`) |
| Q5 | C2 | Licence and holder: MIT / Apache-2.0 / none; holder "Pat Ploypairaoh" (the name on the merge commits) | MIT, 2026, Pat Ploypairaoh; confirm before merging |

## Evidence collected so far

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

Note for the final report: `docs/time-series-readiness.md` links the
parked threshold to this progress file; repoint it when the file is
folded into `portfolio-readiness.md`.
