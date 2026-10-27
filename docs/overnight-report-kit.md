# Overnight run: a report kit for Phase 5, on demo data (Milestone E)

## Report

- **Branch:** `claude/report-kit`, off `main` at `5dde0c7` ("Merge pull request #4 from PloypairaohPat/claude/deploy-kit"). This session's setup named a different working branch; per the brief, everything went to `claude/report-kit`.
- **Commits on top of main `5dde0c7`:** 7, plus this report (listed below). **Pushed:** yes, after every green commit. No force push, nothing to `main`, no PR.
- **STOP conditions:** none held.
  - `5dde0c7` is in main's history.
  - The baseline on clean main was green: **459 passed, 1 skipped**.
  - `alembic heads` showed one head, `a02471448340`.
  - main had no `src/reports/` and no `reports/`.
- **Verification setup:**
  - Local Postgres 16 on 127.0.0.1, with a freshly recreated `jobmarket_test` before every commit.
  - A gate script that **exits on the first failure**: pytest with `TEST_DATABASE_URL`, `ruff check .`, `ruff format --check .`, the alembic upgrade → downgrade → upgrade round trip on a recreated database, and `make views` twice.
  - Versions: Python 3.13.17, SQLAlchemy 2.1.6, alembic 1.20.1, pandas 3.1.0, matplotlib 3.11.2, pytest 9.1.1, ruff 0.17.2, Docker 29.9.2, Compose 5.6.1.
- **Data:** synthetic only. `seed_demo_data.py --full` (its guard untouched) into local `jobmarket_demo` and `jobmarket_test`. No job or government API was called, and no ingestion ran.
- **Compare:** https://github.com/PloypairaohPat/job-market-tracker/compare/main...claude/report-kit?expand=1
- **Afterwards:** the throwaway prod stack used to test `make prod-report` was taken down with its volumes, and its throwaway `.env` and the `reports/` output were deleted. None of them was committed.

| Check | Baseline (clean main) | Final |
|---|---|---|
| `pytest` with `TEST_DATABASE_URL` | 459 passed, 0 failed, 1 skipped | **518 passed, 0 failed, 1 skipped** (+59: guardrails 20, core 18, new views 4, report 1 10, report 2 7). The skip is the Metabase e2e test, which needs `METABASE_URL` |
| `ruff check .` (0.17.2) | clean | clean |
| `ruff format --check .` (0.17.2) | clean | clean, 126 files (ruff 0.17 counts Markdown too) |
| alembic upgrade → downgrade → upgrade on a recreated database | clean | clean (no migration in this milestone) |
| `make views` on a fresh database, twice | 9 views | **12 views**, twice |
| Golden files (reports rendered from hand-built view frames) | — | both match: `tests/fixtures/reports/*.md` |
| End to end on the full demo seed (`python -m src.reports <slug>`) | — | both reports render; provenance row counts equal `count(*)` of each view; no `nan`/`None` |
| `make report` (local) | — | renders both reports into `reports/<slug>/` |
| `make prod-report` (pipeline image, prod stack in Docker, demo data) | — | both reports render, on an image rebuilt from the final code. Run as root, and as uid 1000 writing into its own directory (the server's `deploy` case): the files belong to the invoking user. Without `--user`, the image's uid 10001 gets "Permission denied", which is why the target passes it |
| GitHub Actions CI on the branch | — | runs **#32–#37 all green** (test 3.11, test 3.12, image); this report's push wasn't checked |

## What shipped

| # | Commit | What |
|---|---|---|
| 1 | `646e85d` | Guardrails as code (`src/reports/guardrails.py`) |
| 2 | `0b15b3f` | Report core: views-only reader, provenance stamp, Markdown, charts |
| 3 | `785f490` | Two views for report 1: `v_skill_text_basis`, `v_federal_skill_by_admission` |
| 4 | `6dc4c29` | Report 1: commercial vs federal skill demand; the CLI and catalog |
| 5 | `9977f6f` | `make report`, `make prod-report`, `docs/reports.md`, README |
| 6 | `7b42e45` | Stretch, report 2: how much employers disclose; view `v_field_completeness_counts`; chart legend fix |
| 7 | (this) | This report |

**1. Guardrails.** Each rule from the "Guardrails carried forward" lists in `docs/phase_3_findings.md` became a type the renderers require.

| Type or function | Enforces |
|---|---|
| `Rate` | Can't be built without a denominator; renders as "33.8% (180 of 533 tags)". When a view computed the percentage, the numerator and denominator must reproduce it, which catches a rate quoted against the wrong denominator. Rounding matches Postgres (half up). |
| `Count`, `Ratio`, `Stat`, `Gap` | Always render their n or both terms. `Stat` can carry its IQR. A `Gap` is "+22.8 pp" only in a table row that shows both its rates. |
| `SKILL_FLOOR` | Commercial 15, federal 5, with `apply_floor` (suppress) and `below_floor` (flag). |
| `skill_rate` | Marks commercial (Adzuna) rates truncation-floored. |
| `summarize_salary` | Only the clean population (`v_commercial_salary_clean`, or rows proving `ok`/USD/`year`). Median and IQR; there is no mean. One basis at a time: employer-disclosed or Adzuna-predicted, with no pooled option. |

None of the reports uses salary levels yet, so `summarize_salary` exists for the reports to come; it's fully unit-tested.

**2. Core.**

- `ViewReader` runs `SELECT *` on a `v_*` view defined in `sql/views/` and nothing else, recording row counts. A test checks that no report module reaches the database another way.
- `Provenance` stamps:
  - the database (`current_database()`)
  - the UTC generation time
  - the git commit (`-dirty` when tracked files changed; `REPORT_GIT_COMMIT` overrides)
  - per-view row counts
- A database named `*demo*`/`*test*` gets "Synthetic demo data, not market findings." above the title and in every chart title.
- `Doc` tables accept only counts, labels and guardrail types: a float, or a label that's really a number, is refused. A table showing a commercial skill rate must say "truncation-floored". Narrative sections are `[TO WRITE: ...]` blocks listing that run's numbers.
- `grouped_barh` labels every bar with its full rate. It uses the validated colour pair from the dataviz reference palette (light mode), and renders deterministic PNGs.

**3. Views.**

- `v_skill_text_basis`: per market, what text the extractor read and how many tags it found. It exposes `n_tags`, the denominator of `v_skill_category_composition.pct_of_tags`, which that view never showed.
- `v_federal_skill_by_admission`: federal skill rates by admission route, zero counts included. It regenerates the Statistics-tag circularity check.

Both were tested on hand-built rows and, on the demo seed, against the existing views. Both are documented in the data dictionary.

**4. Report 1** (`commercial-vs-federal-skills`):

- a text-basis table: full text vs at/near the ~500-char cap, length IQR, tags per job
- the category composition, as chart and table, checked against the denominators; categories below the floor are marked ‡
- drill-down tables above the floors, with the count of suppressed skills; commercial rates labelled truncation-floored; federal-fitted taxonomy entries marked †
- **Methods and caveats**:
  - populations and admission routes
  - symmetric truncation
  - taxonomy provenance
  - the Statistics-tag check
  - floors and pooling
- headline, what it means, and what to do about it as placeholders, each listing that run's numbers

**5. Make and docs.**

- `make report REPORT=<slug>`; leaving out `REPORT` lists the reports.
- `make prod-report REPORT=<slug>` runs `python -m src.reports` in the pipeline image against the prod stack's database:
  - `--user` is the invoking user, so the files are theirs
  - `MPLCONFIGDIR=/tmp/matplotlib`
  - the host checkout's commit goes into the provenance stamp (the image has no `.git`)
  - output lands in `./reports/<slug>/`
- `docs/reports.md` covers the laptop and the server, what a report contains, the narrative workflow, the guardrails, and adding a report.
- The README links it, and its Phase 5 roadmap row now says the kit is ready.
- `reports/` is gitignored.

**6. Report 2** (`how-much-employers-disclose`, the stretch):

- **Measured fields:**
  - salary: any figure present vs employer-disclosed vs Adzuna's model estimate
  - skills, location, company, posted date

  As a chart plus a table.
- **Instrument-limited fields** (seniority, metro, remote) get their own section, with the mechanism behind each. Code refuses to chart them, and federal remote shows as "not measurable", never 0%.
- **New view `v_field_completeness_counts`** holds the counts behind `v_field_completeness`'s percentages, so every rate has its numerator. Each render checks that they reproduce the percentage view.
- **Chart fix:** the legend moved above the plot, after the screenshot showed it colliding with a bar label, and no tick runs past 100%. This also changed report 1's chart.

## Sample: Report 1 rendered on demo data

This is `python -m src.reports commercial-vs-federal-skills` on the local `jobmarket_demo` database at the final code commit. It's shown here only; no rendered output is committed. The demo data is synthetic, and its numbers mean nothing:
- its commercial descriptions are about 235 characters, so "at/near the cap" reads 0% where real data reads about 99.7%
- its federal market is 5 postings, so every federal skill falls below the n ≥ 5 floor

The chart, `composition.png`, isn't included. It's a grouped horizontal bar chart of the composition table, each bar labelled with its full rate, with the demo banner in its title.

<details>
<summary>Rendered report.md (demo data)</summary>

```markdown
<!-- Generated by `python -m src.reports commercial-vs-federal-skills`. Every table, chart and number is recomputed from the SQL views on each run, and the file is overwritten: write narrative in a copy (docs/reports.md). -->

> **Synthetic demo data, not market findings.**

# Commercial vs federal skill demand

_Phase 5 report 1. Regenerates Phase 3 Investigation #2 (docs/phase_3_findings.md) from the SQL views._

| Provenance | |
|---|---|
| Database | `jobmarket_demo` |
| Generated at | 2026-10-27 02:24:38 UTC |
| Git commit | `7b42e4553717` |
| Rows in `v_federal_skill_by_admission` | 20 |
| Rows in `v_skill_category_composition` | 8 |
| Rows in `v_skill_text_basis` | 2 |
| Rows in `v_skill_top_by_source` | 20 |

## Headline

> **[TO WRITE: Headline]** One or two sentences on how the two markets' skill mix differs. Base it on the composition comparison (section 2), not the drill-down.
>
> Numbers from this run to draw on:
> - Commercial jobs compared: 609
> - Federal jobs compared: 5
> - Commercial share of tags in language: 39.9% (540 of 1,353 tags)
> - Commercial share of tags in bi_tool: 33.9% (459 of 1,353 tags)
> - Commercial language + bi_tool combined: 73.8% (999 of 1,353 tags)
> - Federal share of tags in bi_tool: 38.5% (5 of 13 tags)
> - Federal share of tags in language: 30.8% (4 of 13 tags)
> - Federal bi_tool + language combined: 69.2% (9 of 13 tags)
> - Largest gap: ml_stats (commercial − federal): -25.0 pp (5.8% (78 of 1,353 tags) vs 30.8% (4 of 13 tags))
> - Largest gap: data_tool (commercial − federal): +10.2 pp (10.2% (138 of 1,353 tags) vs 0.0% (0 of 13 tags))
> - Largest gap: database (commercial − federal): +10.2 pp (10.2% (138 of 1,353 tags) vs 0.0% (0 of 13 tags))

## 1. Who is compared

**Commercial** is every Adzuna posting. **Federal** is every USAJobs posting classified in scope (`jobs.in_scope`). Skill tags are the taxonomy extractor's, at confidence ≥ 0.8. Each market is described on its own; nothing is pooled across them.

Text basis, from `v_skill_text_basis`.

| Market | Jobs | Read from full text | Read at/near the ~500-char cap (≥ 480) | Description length, chars (median) | Jobs with ≥ 1 tag | Tags | Tags per job |
|---|---|---|---|---|---|---|---|
| commercial | 609 | 0.0% (0 of 609 jobs) | 0.0% (0 of 609 jobs) | 235 (IQR 224–244; n=609) | 100.0% (609 of 609 jobs) | 1,353 | 2.22 (1,353 tags / 609 jobs) |
| federal | 5 | 100.0% (5 of 5 jobs) | 0.0% (0 of 5 jobs) | 5,739 (IQR 5,345–10,564; n=5) | 100.0% (5 of 5 jobs) | 13 | 2.60 (13 tags / 5 jobs) |

## 2. Skill-category composition (the primary comparison)

Each market's skill tags, split by taxonomy category, as a share of **that market's own tags**. Federal descriptions are far longer than Adzuna's, so raw rates would mostly measure how much text each source has; shares compare what each market's text emphasizes. Read the margins as directional (see Methods and caveats).

![Grouped bars: share of each market's skill tags by category](composition.png)

From `v_skill_category_composition`; denominators from `v_skill_text_basis.n_tags`.

| Category | Commercial share of tags | Federal share of tags | Gap (commercial − federal) |
|---|---|---|---|
| language | 39.9% (540 of 1,353 tags) | 30.8% (4 of 13 tags) | +9.1 pp |
| bi_tool | 33.9% (459 of 1,353 tags) | 38.5% (5 of 13 tags) | -4.6 pp |
| data_tool | 10.2% (138 of 1,353 tags) | 0.0% (0 of 13 tags) | +10.2 pp |
| database | 10.2% (138 of 1,353 tags) | 0.0% (0 of 13 tags) | +10.2 pp |
| ml_stats | 5.8% (78 of 1,353 tags) | 30.8% (4 of 13 tags) | -25.0 pp |

‡ on the chart: a category with fewer tags than the market's drill-down floor (commercial n ≥ 15, federal n ≥ 5). Shown, but read it as directional. Here: federal data_tool, federal database, federal language, federal ml_stats.

## 3. Skill drill-down (directional texture)

Individual skills, as a share of each market's jobs. This is texture, not the finding: it is never presented at the composition comparison's confidence, and it stays a table on purpose. Only skills at or above the reporting floor are shown. † marks taxonomy entries added while reading federal postings.

### Commercial (n ≥ 15)

From `v_skill_top_by_source`, top 15 at most.

| Skill | Category | Share of jobs (truncation-floored) |
|---|---|---|
| SQL † | language | 46.8% (285 of 609 jobs) |
| Python | language | 29.1% (177 of 609 jobs) |
| Excel | bi_tool | 28.6% (174 of 609 jobs) |
| Snowflake | database | 22.7% (138 of 609 jobs) |
| dbt | data_tool | 22.7% (138 of 609 jobs) |
| Looker | bi_tool | 19.7% (120 of 609 jobs) |
| Tableau | bi_tool | 16.3% (99 of 609 jobs) |
| R | language | 12.8% (78 of 609 jobs) |
| Statistics | ml_stats | 12.8% (78 of 609 jobs) |
| Power BI | bi_tool | 10.8% (66 of 609 jobs) |

### Federal (n ≥ 5)

No federal skill reaches the n ≥ 5 floor.

10 more federal skill(s) below n ≥ 5 are not shown.

## What it means

> **[TO WRITE: What it means]** Why the mixes differ, and how far the measurement itself can explain it (text basis, truncation, taxonomy provenance, the Statistics check).
>
> Numbers from this run to draw on:
> - Commercial tags per job: 2.22 (1,353 tags / 609 jobs)
> - Commercial median description length, characters: 235 (IQR 224–244; n=609)
> - Federal tags per job: 2.60 (13 tags / 5 jobs)
> - Federal median description length, characters: 5,739 (IQR 5,345–10,564; n=5)
> - Commercial jobs read at or near the ~500-character cap (≥ 480): 0.0% (0 of 609 jobs)
> - Federal jobs read from full text: 100.0% (5 of 5 jobs)
> - Statistics-tagged in series:Operations Research: 100.0% (2 of 2 jobs)
> - Statistics-tagged in skill_density:Management And Program Analysis: 0.0% (0 of 3 jobs)
> - Federal-fitted taxonomy entries tagged on federal jobs (of 5): 2

## What to do about it

> **[TO WRITE: What to do about it]** What a job seeker (or this project) should do with the contrast. Keep skill-level advice at drill-down confidence.
>
> Numbers from this run to draw on:
> - Commercial: SQL †: 46.8% (285 of 609 jobs)
> - Commercial: Python: 29.1% (177 of 609 jobs)
> - Commercial: Excel: 28.6% (174 of 609 jobs)
> - Commercial: Snowflake: 22.7% (138 of 609 jobs)
> - Commercial: dbt: 22.7% (138 of 609 jobs)
> - Commercial skills below the n ≥ 15 floor, not shown: 0
> - Federal skills below the n ≥ 5 floor, not shown: 10
> - (commercial skill rates are truncation-floored)

## Methods and caveats

- Commercial jobs (every Adzuna posting): 609
- Federal jobs (USAJobs postings classified in scope): 5
- Federal jobs admitted via `series:Operations Research`: 2
- Federal jobs admitted via `skill_density:Management And Program Analysis`: 3
- Skill tags: the curated-taxonomy extractor (`src/cleaning/skill_extractor.py`) over the title plus the full description (federal) or Adzuna's description (commercial), at confidence ≥ 0.8 in every view used.
- Composition, not magnitude: shares of each market's own tags, because the two sources carry very different amounts of text (median description length below).
- Commercial median description length, characters: 235 (IQR 224–244; n=609)
- Federal median description length, characters: 5,739 (IQR 5,345–10,564; n=5)

### Truncation cuts both ways

- Commercial jobs read at or near Adzuna's ~500-character cap (≥ 480 chars): 0.0% (0 of 609 jobs)
- Federal jobs read from full announcement text: 100.0% (5 of 5 jobs)
- Commercial skill rates are **truncation-floored**: a skill cut off by the cap is missing, so a low commercial rate or rank may be an artifact, not low demand.
- Commercial's composition isn't a neutral baseline either: the first ~500 characters of a posting may favour workflow and BI tools and push languages and ML/statistics later, past the cap. That mechanism is measured on the federal side only. Treat the margins as a floor on the true contrast, not the contrast itself (docs/findings_commercial_vs_federal_skills.md).

### Taxonomy provenance

These entries were added while reading federal postings, so the federal side reflects an instrument partly built from federal text († in the drill-down):

| Entry | Change | Federal jobs tagged in this data |
|---|---|---|
| SQL | alias 'structured query language' added | 1 |
| SPSS | new skill | 1 |
| GIS | new skill | 0 |
| SSIS | new skill | 0 |
| SSRS | new skill | 0 |

### Statistics-tag check

Is the federal ml_stats share just the occupational-series label echoed back? If the Statistics tag rate holds in a route admitted by series code without a statistics label (Operations Research), it isn't. From `v_federal_skill_by_admission`.

| Admission route | Statistics-tagged jobs | Note |
|---|---|---|
| `series:Operations Research` | 100.0% (2 of 2 jobs) | below the federal n ≥ 5 floor: directional |
| `skill_density:Management And Program Analysis` | 0.0% (0 of 3 jobs) | below the federal n ≥ 5 floor: directional |

### Reporting floors and pooling

- Skill drill-down floors: commercial n ≥ 15, federal n ≥ 5 (docs/phase_3_findings.md). Rows below are not shown; composition categories below are shown and marked.
- Commercial drill-down rows suppressed: 0
- Federal drill-down rows suppressed: 10
- Every number is per market; nothing is pooled across commercial and federal.
- Sources: `sql/views/v_skill_category_composition.sql`, `v_skill_text_basis.sql`, `v_skill_top_by_source.sql`, `v_federal_skill_by_admission.sql`; docs/phase_3_findings.md (Investigation #2); docs/findings_commercial_vs_federal_skills.md.
```

</details>

## Parked questions

| Q | Question | Recommendation (built) |
|---|---|---|
| 1 | Where the written narrative lives, and whether regeneration keeps it | (a) copy the render and write in the copy |
| 2 | The placeholder marker | (a) a visible `**[TO WRITE: <section>]**` |
| 3 | "At or near the cap" threshold | (a) description-only text ≥ 480 characters |
| 4 | Small groups: suppress or flag | (a) suppress in drill-downs, flag (‡) in the composition |
| 5 | Truncation label on commercial composition shares | (a) no; the label goes on rates of jobs, and shares carry the symmetric-placement caveat |
| 6 | Which numbers sit beside the headline | (a) generic (top two categories, largest gaps), not Phase 3's fixed pairs |
| 7 | Granularity of the Statistics-tag check | (a) one row per admission route, not Phase 3's grouped buckets |
| 8 | Recording which taxonomy entries are federal-fitted | (a) a constant in the report, tested against `skills.json` |
| 9 | Federal remote in report 2 | (a) "not measurable", never 0% |
| 10 | Skills present: any confidence (report 2) vs ≥ 0.8 (report 1) | (a) keep each view's definition and say so in Methods |
| 11 | The commit stamp on the server | (a) the host checkout's, marked "(host checkout)" |
| 12 | Where finished reports with real numbers are published | (a) undecided: rendered drafts stay in gitignored `reports/` |
| 13 | Drill-down length | (a) at most 15 skills per market above the floor |

### Q1. Where the narrative lives
- **What I found:** a render is overwritten every run, and your narrative must survive regeneration on new data.
- **Options:**
  - (a) Copy the rendered report and write in the copy; re-render to refresh the numbers and update the copy by hand (documented in `docs/reports.md`).
  - (b) A committed narrative file per report (e.g. `docs/reports/<slug>.narrative.md`) that the renderer merges into the `[TO WRITE]` blocks.
  - (c) The renderer preserves text inside the blocks of an existing render.
- **Recommendation:** (a) now. (b) once you've written the first one and know the shape you want; it's about a day's work with tests.

### Q2. The placeholder marker
- **What I found:** the marker must be impossible to miss in a draft and easy to grep for.
- **Options:**
  - (a) A visible bold `[TO WRITE: <section>]` blockquote.
  - (b) HTML comments (invisible when rendered, so easy to publish by mistake).
  - (c) An emoji marker.
- **Recommendation:** (a).

### Q3. "At or near the cap"
- **What I found:** `docs/findings_field_completeness.md` says 1,479 of 1,483 (99.7%) commercial descriptions sit "at/near a hard 500-char cap", but doesn't record the threshold used.
- **Options:**
  - (a) Description-only text ≥ 480 characters (`v_skill_text_basis.n_near_cap`).
  - (b) ≥ 495 (strictly at the cap).
  - (c) ≥ 450.
- **Recommendation:** (a). Check it reproduces about 99.7% on your data, and if it doesn't, move the threshold in the view and in `skill_demand.NEAR_CAP_CHARS` (a test keeps them together).

### Q4. Small groups
- **What I found:** Phase 3 applied n ≥ 15 / n ≥ 5 to skill drill-downs only. Its composition table showed every category, including federal `cloud` at n = 3.
- **Options:**
  - (a) Suppress drill-down rows below the floor (with a count of what was hidden), and show composition categories but mark them ‡.
  - (b) Suppress everywhere.
  - (c) Flag everywhere.
- **Recommendation:** (a). The ‡ in the composition is a new, cautious addition.

### Q5. Truncation label on composition shares
- **What I found:** a truncation-floored *rate* can only be too low. A commercial composition *share* can be too high or too low (the methods note's symmetric caveat).
- **Options:**
  - (a) Label rates of jobs truncation-floored, and give the composition the symmetric-placement caveat.
  - (b) Label every commercial skill number truncation-floored.
- **Recommendation:** (a).

### Q6. Headline numbers
- **What I found:** Phase 3's headline paired workflow + bi_tool (commercial) with ml_stats + language (federal). On new data the leading categories may change.
- **Options:**
  - (a) Generic: each market's two largest categories, their combined share, and the three largest gaps.
  - (b) Phase 3's fixed pairs.
  - (c) Both.
- **Recommendation:** (a). The numbers follow the data, and you decide what the headline claims.

### Q7. The Statistics-tag check
- **What I found:** Phase 3 grouped series 1530/1560 into one bucket. `scope_reason` stores the series *label*, so the view shows Statistics, Data Science Series and Operations Research separately, plus the skill-density route.
- **Options:**
  - (a) One row per route.
  - (b) Group the two statistics-labelled series like Phase 3.
- **Recommendation:** (a). The non-circularity test only needs the Operations Research row, and you can add the other two by hand.

### Q8. Federal-fitted taxonomy entries
- **What I found:** `skills.json` doesn't record why an entry was added.
- **Options:**
  - (a) A constant in `skill_demand.py` (SQL alias, SPSS, GIS, SSIS, SSRS), with a test that each exists in the taxonomy.
  - (b) An `added_for` field in `skills.json`.
- **Recommendation:** (a). (b) is cleaner, but it touches the cleaning layer's data.

### Q9. Federal remote
- **What I found:** the classifier never reads `description_full`, where federal telework policy sits. Phase 3's guardrail says not to chart federal 0.0% beside commercial.
- **Options:**
  - (a) "not measurable".
  - (b) 0.0% with a caveat.
- **Recommendation:** (a), built into the code.

### Q10. Skills present: two definitions
- **What I found:** `v_field_completeness` counts a tag at any confidence. The skill-demand views use ≥ 0.8.
- **Options:**
  - (a) Keep each view's definition and say so in report 2's Methods.
  - (b) Change `v_field_completeness` to ≥ 0.8. That changes an existing view and the Transparency dashboard.
- **Recommendation:** (a).

### Q11. The commit stamp on the server
- **What I found:** the image has no `.git` (by design), so `make prod-report` passes the server checkout's commit. It matches the running code only if `make prod-build` ran after the last `git pull`.
- **Options:**
  - (a) Host checkout, marked "(host checkout)".
  - (b) Bake the commit into the image at build time. That's a Dockerfile change, part of the deploy kit (out of scope).
- **Recommendation:** (a) now, (b) with the next deploy-kit change.

### Q12. Publishing finished reports
- **What I found:** rendered reports carry real numbers. The brief keeps them out of the repo, but the portfolio needs them somewhere.
- **Options:**
  - (a) Decide when the first one is written. Drafts stay in gitignored `reports/`.
  - (b) Commit finished reports under `docs/reports/` (public repo, real numbers).
  - (c) A blog or a separate repo.
- **Recommendation:** (a).

### Q13. Drill-down length
- **Options:**
  - (a) At most 15 skills per market above the floor.
  - (b) All of them above the floor.
  - (c) 10.
- **Recommendation:** (a). It keeps the texture subordinate to the composition.

## What you need to do: regenerate on real data

Nothing here touched your data. On the laptop, after merging the PR:

```powershell
git checkout main
git pull
uv sync
uv run python scripts/apply_views.py                          # the kit adds three views (12 in all)
uv run python -m src.reports commercial-vs-federal-skills     # or: make report REPORT=...
uv run python -m src.reports how-much-employers-disclose
```

Then:

- [ ] Open `reports\<slug>\report.md` and check the stamp: database `jobmarket`, no demo banner, your commit.
- [ ] Sanity-check report 1 against `docs/phase_3_findings.md`'s Investigation #2 tables. The numbers will have moved as the data grew, but the shape should be recognisable.
- [ ] Check that "at/near the cap" comes out around 99.7% (Q3).
- [ ] Copy each report and write the three `[TO WRITE]` sections (`docs/reports.md`, "Writing the narrative").
- [ ] Optional: `uv run python -m src.dashboard.reader_role` lets Metabase's reader see the three new views. No dashboard uses them.

If a report stops with a guardrail error, the message names the rule. It means a view and the report disagree; tell me what it says rather than working around it.

**On the server**, after the cut-over:

```bash
git pull
make prod-build
make prod-views
make prod-report REPORT=<slug>
```

The output lands in `~/job-market-tracker/reports/`.

## Surprises

- **Two views showed rates without their numerators.** `v_skill_category_composition` computes `pct_of_tags` against a denominator it doesn't expose, and `v_field_completeness` has percentages only. Reverse-engineering counts from rounded percentages would be ambiguous above about 1,000 jobs, so both got companion views. The reports cross-check the old percentages against the new counts on every render.
- **Rounding differs between Postgres and Python.** Postgres rounds half up and Python half to even, so a recomputed 0.25 would print 0.2 where the view says 0.3. The guardrails round like Postgres and prefer the view's own figure.
- **pandas wraps database errors.** It raises its own `DatabaseError`, so a missing view first surfaced as a raw traceback. The reader now says "Run `make views` first."
- **Looking at the charts caught what tests didn't.** Report 2's first chart had the legend sitting on a bar label, and an axis running to 140%. Both are fixed for every chart.
- **The golden file caught a bug in my own test fixture.** Report 2's fixture listed counts in a different order from the fields, so "posted date" came out as 9%. Reviewing the generated golden caught it; the fixture is now keyed by field name.
- **`Ratio` printed "1,353.0"** for a whole-number float. A unit test caught it.
- **Container permissions.** The image runs as uid 10001, which can't write into the `deploy` user's directory, hence `--user` on `make prod-report`. I proved it both ways in Docker.
- **The demo data is the wrong shape for these questions.** Its federal market is 5 postings and its commercial descriptions are about 235 characters, so the floors, flags and "not shown" counts are exercised, but the truncation side isn't. The golden fixtures cover the realistic shapes with invented numbers.

**How I know no live API was called:**

- No ingestion ran: every database was filled by `seed_demo_data.py --full`, which uses fixture-backed clients.
- No command in this run named an Adzuna, USAJobs or DOL host.
- Network use was:
  - GitHub (`git push`, the GitHub MCP for CI status)
  - PyPI (`pip install .` inside the two `docker build`s)
  - possibly Docker Hub metadata lookups for the cached base image; no image was pulled

## Suggested PR title

**Phase 5 report kit: guardrails as code, views-only renderer, reports 1 and 2 on demo data**

<details>
<summary>PR description (ready to paste)</summary>

## Summary

Milestone E: the machinery that turns the SQL views into a written report with one command, so Phase 5's reports can be regenerated on real data whenever it grows. No findings are written: the narrative sections are placeholders, each with the numbers from that run.

- **Guardrails as code** (`src/reports/guardrails.py`), from Phase 3's "Guardrails carried forward":
  - every grouped number renders with its n, and a rate can't exist without its denominator; when the view computed the percentage, it's cross-checked against the counts
  - salary: clean population only, median + IQR (no mean), disclosed and predicted never pooled
  - drill-down floors (commercial n ≥ 15, federal n ≥ 5): suppressed and counted; composition categories below the floor are flagged
  - commercial skill rates are labelled truncation-floored
- **Views-only renderer:**
  - `ViewReader` reads whole `v_*` views and nothing else
  - a provenance stamp: database, UTC time, git commit, rows per view
  - a demo banner on `demo`/`test` databases
  - Markdown tables that refuse unguarded numbers
  - matplotlib PNGs labelled with full rates
- **Three views:**
  - `v_skill_text_basis`
  - `v_federal_skill_by_admission`
  - `v_field_completeness_counts` (the numerators and denominators the reports need)
- **Report 1, commercial vs federal skill demand** (Investigation #2):
  - text basis
  - composition chart and table
  - drill-downs above the floors
  - Methods and caveats: truncation, taxonomy provenance, the Statistics-tag check
  - `[TO WRITE]` headline, what it means, and what to do
- **Report 2, how much employers disclose** (Investigation #3):
  - measured vs instrument-limited fields kept apart
  - instrument-limited fields never charted
  - federal remote "not measurable"
- **Commands:** `make report REPORT=<slug>` and `make prod-report REPORT=<slug>` (in the pipeline image, as the invoking user). Docs in `docs/reports.md`; README Documentation and Phase 5 row updated.

## Testing

- `pytest` with `TEST_DATABASE_URL`: 459 → **518 passed**, 1 skipped.
- `ruff check .` / `ruff format --check .` (0.17.2) clean; alembic round trip clean; `make views` applies 12 views, twice.
- Golden files for both reports, rendered from hand-built frames with invented numbers.
- Unit tests for every guardrail.
- End-to-end CLI runs on the full demo seed.
- `make prod-report` verified in Docker against the prod stack on demo data, including as a non-root uid.
- No job or government API was called, and no rendered output is committed.

## Open questions

13 parked decisions are in `docs/overnight-report-kit.md`, each with the default that was built:
- where the narrative lives
- the placeholder marker
- the near-cap threshold
- suppress vs flag
- the truncation label on shares
- headline numbers
- the Statistics-check granularity
- federal-fitted entries
- federal remote
- the two skills-present definitions
- the server commit stamp
- publishing
- drill-down length

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01ATh4ABgiML8G58MzgJ36ZP

</details>
