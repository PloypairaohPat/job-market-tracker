# Overnight run: daily clock, laptop doctor, Report 3 improvements, Report 4 (salaries), alias helper

## Report

- **Branch:** `claude/overnight-batch`, off `main` at `4dfd129` ("Merge pull request #7 from PloypairaohPat/claude/lca-loader-fix"). This session's setup named a different working branch; per the brief, everything went to `claude/overnight-batch`.
- **Commits on top of main `4dfd129`:** 21, plus this report (listed below). **Pushed:** yes, after every green commit. No force push, nothing to `main`, no PR.
- **How far I got:** **all six parts are complete**, A to F, F being the stretch. Nothing is partial or not started.
- **STOP conditions:** none held.
  - `4dfd129` is in main's history (main's head).
  - The baseline on clean main was green: **577 passed, 1 skipped**.
  - `alembic heads` showed one head, `a02471448340`.
  - Main had no `src/reports/salary.py`, no `what-postings-pay` slug, no `src/doctor.py` or `src/doctor/`, and no `claude/overnight-batch` branch.
- **Verification setup:**
  - Local Postgres 16 on 127.0.0.1, with a freshly recreated `jobmarket_test` before every commit.
  - A gate script that **exits on the first failure**: pytest with `TEST_DATABASE_URL`, `ruff check .`, `ruff format --check .` (0.17.2), the alembic upgrade → downgrade → upgrade round trip on a recreated database, `make views` twice, and `shellcheck` on every changed shell script (`scripts/run_daily.sh`). It stopped twice at `ruff format`, and once on a test that hadn't been updated for a new section; I fixed each and re-ran the whole gate before committing.
  - Versions: Python 3.13.17, SQLAlchemy 2.1.6, alembic 1.20.1, pandas 3.1.0, matplotlib 3.11.2, pytest 9.1.1, ruff 0.17.2, shellcheck from `shellcheck-py`.
- **Data:** synthetic only: `seed_demo_data.py --full` (guard untouched) into local `jobmarket_demo` and `jobmarket_test`, and hand-built rows and frames in tests. No ingestion ran, and no job or government site was called.
- **Charts:** I looked at every chart before committing: Report 4's two box charts, and Report 3's unchanged bar charts after its changes.
- **Compare:** https://github.com/PloypairaohPat/job-market-tracker/compare/main...claude/overnight-batch?expand=1

| Check | Baseline (clean main) | Final |
|---|---|---|
| `pytest` with `TEST_DATABASE_URL` | 577 passed, 0 failed, 1 skipped | **693 passed, 0 failed, 1 skipped** (+116). The skip is the Metabase end-to-end test, which needs `METABASE_URL` |
| `ruff check .` (0.17.2) | clean | clean |
| `ruff format --check .` (0.17.2) | clean, 134 files | clean, 147 files (Markdown included, this report too) |
| alembic upgrade → downgrade → upgrade on a recreated database | clean | clean (no migration) |
| `make views` on a fresh database, twice | 17 views | **22 views**, twice (`v_employer_roles`, `v_lca_monthly`, `v_salary_population`, `v_salary_skill_coverage`, `v_skill_category_composition_roles`; `v_matched_employer_lca_wages` extended at the end) |
| `shellcheck scripts/run_daily.sh` | — | clean |
| Golden files | 3 | 4: `employers-and-sponsorship` and `commercial-vs-federal-skills` updated (every diff reviewed), `what-postings-pay` new, `how-much-employers-disclose` unchanged. C1's `<0.1%` / `>99.9%` changed no golden: every 100.0% in them is an exact whole |
| `.ps1` parse check with pwsh | — | **not run.** `apt-get install powershell` found no package; the release tarball downloaded from GitHub, but running it was blocked by this session's permission policy. Tests check the `.ps1` statically instead (ASCII only, docker before Python, only the pipeline's exit code returned) |
| Real-figure grep (`git diff main -U0` for the Phase 3 salary figures) | — | prints nothing |
| The brief's `git grep` for personal data (email addresses, Windows user paths) | nothing | nothing new |
| `git diff main --stat` | — | no data, log, rendered report, PNG, `.env`, `uv.lock` or `company_aliases.json` change |
| GitHub Actions CI on the branch | — | **#56–#75 green (one per commit, A1 through E2); #76 (F1) was still running when this was written** |

## What shipped

| Part | Commit | What |
|---|---|---|
| A1 | `5091dd9` | `restart: unless-stopped` on the compose `db` service only |
| A2 | `2409774` | The daily runner waits for the database (`--db-wait`, default 300 s) and exits 2 if it never comes up |
| A3 | `c44e97e` | `run_daily.ps1` and `run_daily.sh` run `docker compose up -d db` first |
| A4 | `07e7e04` | Health check H7, missing days |
| A5 | `b0b281a` | daily-operation.md: exit codes, after a reboot or wake, how to tell the clock is running, missed days |
| B1 | `aeb3324` | `python -m src.doctor` (and `make doctor`): ten read-only checks, each with its fix |
| B2 | `b26d4db` | `docs/laptop-runbook.md`, linked from the README and daily-operation.md |
| C1 | `ca622b0` | `Rate.render()`: `<0.1%` and `>99.9%` |
| C2 | `0cd6386` | `v_employer_roles`; distinct titles, locations, the role share and the repeat share in Report 3 |
| C3 | `fb68733` | Report 3's federal framing: the no-analytics note and a Methods caveat |
| C4 | `81c70ad` | `v_lca_monthly`; LCA coverage of the filing window in Report 3's Methods |
| C5 | `795f50a` | Wage robustness columns (appended last) and rows in Report 3 |
| C6 | `8e6dc21` | Docs for Part C |
| D0 | `5738cd6` | Salary guardrails: `SALARY_FLOOR`, `FlooredSalary`, `SalaryDiff`, `check_salary_wording` |
| D1 | `4008ba5` | `v_salary_population`, `v_salary_skill_coverage` |
| D2, D3 | `a294d86` | Report 4, `what-postings-pay`, with its golden, unit and end-to-end tests |
| D4 | `1b20b44` | Docs for Part D |
| E1 | `9f94c98` | `python -m src.cleaning.aliases apply` |
| E2 | `9341a2d`, `2920bb6` | Docs use the helper; the manual edit is kept as a fallback |
| F1 | `94d0e1f` | `v_skill_category_composition_roles` and Report 1's "Sensitivity: distinct roles" table |
| — | (this) | This report |

### Part A: keep the daily clock running

- **A1.** `docker-compose.yml`'s `db` gains `restart: unless-stopped`; Metabase is unchanged. `docker compose config` shows the policy on `db` only, with and without `--profile bi`. docs/daily-operation.md says the next `docker compose up -d db` recreates the container with the policy and keeps the `jobmarket_pg_data` volume.
- **A2.** Before the advisory lock, `run_daily` tries to connect at once, then every 10 s for up to `--db-wait` seconds.
  - Each attempt is logged with `host:port` only. Error text is cut to its first line, and the URL and password are masked.
  - If the database never answers, stdout and the dated log get: `database unreachable at <host>:<port> after N s; is Docker Desktop running? Then: docker compose up -d db`. Then the summary with a `db` FAIL line, the failure ping (if configured, and not on a dry run), and **exit code 2**.
  - The connect function and the sleep are injectable. Tests cover reachable at once, on the 3rd attempt (unit and against the test database), never (exit 2, message in stdout and log, no password), and `--db-wait 0`. The existing daily-runner tests pass unchanged.
- **A3.** Both run scripts run `docker compose up -d db` when `docker` is on PATH, print one line (ran / failed / not found), ignore its failure, and still return only the pipeline's exit code. `run_daily.sh` is tested for real from a temp copy with a fake `docker` and a fake venv python. The `.ps1` stays ASCII only.
- **A4.** H7 "missing days" lists the UTC dates in the last 14 days with no snapshot. Today is excluded, because its run may not have happened yet, and nothing before the first snapshot counts. Past 14 dates it shows a count with the first and last. It never FAILs. Tests use a fixed `now`. Two existing health tests now expect H7: one of them seeds a deliberate gap and used to assert every check PASSes.
- **A5.** New sections in docs/daily-operation.md:
  - Exit codes: 0, 1 and 2, as LastTaskResult shows them
  - After a reboot or wake: Docker Desktop's "Start Docker Desktop when you sign in to your computer", the restart policy, and the wait
  - How to tell the clock is running: H7, `Get-ScheduledTaskInfo` (0 / 267011), and the logs
  - If a day was missed: it can't be backfilled; save today, then find why

### Part B: the laptop doctor

`python -m src.doctor` (`make doctor`, `--json`) is read-only and never prints a secret value. Each check prints a status, a one-line finding and, when something's wrong, the exact fix (PowerShell, plus a POSIX form where it differs). The checks, in order:

1. `.env`. Includes NUL bytes → FAIL "re-save .env as UTF-8 in Notepad"; variable names only.
2. Database (5 s). A FAIL skips 3, 4, 5 and 7.
3. Migrations, via alembic's API.
4. Views.
5. The daily clock: H1, H2, H7, the streak, snapshot days.
6. The scheduled task (Windows; `schtasks` output parsed; 0 and 267011 explained).
7. LCA data: missing months listed per non-latest FY, and `data/lca/` files whose FY isn't loaded, with the loader command.
8. Files in the wrong place: untracked `.xlsx` / `.csv` / `.dump` / `.log` outside `data/` and `logs/` → FAIL with `Move-Item`.
9. VIRTUAL_ENV: INFO only.
10. Untracked `uv.lock`: INFO only, with no advice to commit it.

Exit 1 on any FAIL. A check that crashes is a FAIL naming the error type, never a traceback. The tests cover every check's problem path and its fix: fakes for `.env`, schtasks and git output (invented values), and the test database for migrations, views, the clock and LCA. Also a read-only check and a run on the demo seed. docs/laptop-runbook.md covers the routine after every pull, a weekly routine, where files go, the eight troubleshooting rows, and (from Part E) reviewing matches.

### Part C: Report 3

- **C1.** A nonzero rate that rounds to 0.0 renders `<0.1%`, and a rate short of the whole that rounds to 100.0 renders `>99.9%`. `Rate.value` is unchanged.
- **C2.** `v_employer_roles`: `n_postings`, `n_roles`, `n_locations`, `market_n_postings` and `market_n_roles` per (market, employer).
  - It has the same populations and the same NULL-employer row as `v_employer_postings`. That row has postings but 0 roles.
  - Section 2 gains Distinct titles and Locations in the top-10 table.
  - New lines: the share of distinct roles from the top 10 by roles (its own ranking), and postings that repeat a role already counted.
  - Both shares are in the headline numbers, and Methods carries the undercount / overcount caveat.
- **C3.** When a market's matched employers have no certified analytics-SOC H-1B filing, a note follows the match table: "matched employers' filings in this window include no analytics-SOC H-1B filings". Methods gains the federal citizenship caveat, with the federal closed share from the data. No employer is named in a sponsorship section.
- **C4.** `v_lca_monthly`, and "LCA coverage of the filing window" in Methods: each window FY's months, date range and filings. It flags a partial FY, and any month under 10% of its FY's median month ("unusually few decisions; cause not established"). Without LCA data it says "LCA data not loaded".
- **C5.** `v_matched_employer_lca_wages` gains four columns **at the end**: `median_excl_largest_filer`, `n_filings_excl_largest_filer`, `median_of_employer_medians` and `n_employers_for_median_of_medians`. On the demo seed, its existing columns are identical to main's view (compared row for row), and the pinned-rules test still passes. Section 5 gains a "Robustness check" table with its n.
- **C6.** Docs: reports.md, the data dictionary, and the README view count.

### Part D: Report 4, `what-postings-pay`

- **D0.** Additions to `guardrails.py`; existing behaviour is unchanged.
  - `SALARY_FLOOR = 15`.
  - `FlooredSalary` shows n but withholds the median below the floor.
  - `SalaryDiff` takes two summaries of different bases, or one basis and two groups. It shows both medians and both n, and is refused below the floor or at n = 0.
  - `check_salary_wording` refuses "mean", "average" or "avg" outside `MEDIAN_RATIONALE`.
- **D1.** `v_salary_population`: every commercial posting by quality, currency, period and basis, NULLs as their own groups, plus `in_clean_population`. Its clean total equals `count(*)` of `v_commercial_salary_clean` (tested, and on the demo). `v_salary_skill_coverage`: per basis, the tag share at confidence ≥ 0.8, the largest single-skill n, and the skills at n ≥ 15.
- **D2, D3.** `src/reports/salary.py`, with the nine sections from the brief.
  - Disclosed and predicted are never pooled. The headline's only salary figure is the disclosed median.
  - "No title signal" and "not on the tracked metro list" are their own rows.
  - The box charts draw one summary per box, at n ≥ 15, with no outlier points.
  - Tests:
    - a golden file from invented frames, plus a separate frame where the disclosed basis reaches the floor
    - never pooled, the floor, `SalaryDiff` refusals, no mean, and no titles or job ids
    - the empty path, which renders "no data"
    - the demo end to end: banner, provenance counts, section 2's n equal to the disclosed `count(*)`, and both charts
- **D4.** reports.md (the row, plus the floor and `SalaryDiff` in the guardrails table), the data dictionary, the README (four reports), and the runbook's re-render loop.

### Part E: the alias helper

`python -m src.cleaning.aliases apply --from <csv> [--write]` works on either candidate CSV, detected by its header.

- **Approval:** only `approved` = y / yes / x / 1 / true counts. `keep_a`/`keep_b` (`keep_company`/`keep_lca`) choose the survivor; otherwise the longer key maps onto the shorter.
- **Validation:** each pair is checked: non-empty, normalized keys; no self-map, conflict, chain or cycle. A refused row comes with its reason.
- **Dry run (the default):** prints the plan, the refusals and the JSON diff.
- **`--write`:** keeps `_meta`, the comments, the order, the indent, UTF-8 and the trailing newline. It appends new keys sorted, then prints the follow-up commands. A second run adds nothing.
- **Normalizer:** `company_normalizer.rule_key` was split out of `normalize_company_name`, with identical behaviour.
- **Tests:** temp copies only. The repo's `company_aliases.json` is hashed before and after every test.
- **Docs:** src/visa/README.md step 4, src/cleaning/README.md and the runbook use the helper, and keep the hand edit as a fallback.

### Part F (stretch): distinct roles in Report 1

`v_skill_category_composition_roles` has the composition view's five columns, counted over distinct (market, employer, normalized title) roles: a role carries a category if any of its postings is tagged with it. Report 1 gains "Sensitivity: distinct roles" right after the primary composition, with postings and roles side by side and each n. A test shows the headline and the primary numbers don't move when the roles view changes, and the golden diff adds only the provenance row and the new block.

## Samples (synthetic demo data)

All of this comes from the local `jobmarket_demo` (`seed_demo_data.py --full`) at the final code commit. It's synthetic, and the numbers mean nothing. The LCA rows belong to FAKE employers, and the company names beside posting counts come from the Adzuna test fixtures. No rendered output is committed.

<details>
<summary>Report 3, the changed sections (synthetic demo data)</summary>

#### 2. Who posts analyst jobs

##### Commercial

- Share of commercial postings from the top 10 employers: 83.7% (510 of 609 postings)
- Share of distinct commercial roles from the top 10 employers by roles (their own ranking): 80.5% (66 of 82 roles)
- Commercial postings that repeat a role already counted: 85.4% (479 of 561 postings with a company)

_(chart top-employers-commercial.png not committed: Bars: the top commercial employers' share of postings)_

Postings with no company are never an employer; they stay in the denominator. Concentration counts postings, not hires. Distinct titles and locations are from `v_employer_roles`: many postings with few titles means the same role reposted.

| Rank | Employer | Postings (share of the market) | Distinct titles | Locations |
|---|---|---|---|---|
| #1 | Deloitte | 12.8% (78 of 609 postings) | 11 | 8 |
| #2 | Meta | 11.8% (72 of 609 postings) | 8 | 8 |
| #3 | Capital One | 9.9% (60 of 609 postings) | 8 | 7 |
| #4 | CVS Health | 8.9% (54 of 609 postings) | 8 | 5 |
| #5 | MITRE | 7.9% (48 of 609 postings) | 7 | 6 |
| #6 | Peraton | 7.9% (48 of 609 postings) | 4 | 6 |
| #7 | TekSystems | 7.9% (48 of 609 postings) | 6 | 4 |
| #8 | Acme Analytics | 5.9% (36 of 609 postings) | 4 | 5 |
| #9 | Geico | 5.9% (36 of 609 postings) | 6 | 6 |
| #10 | Insight Global | 4.9% (30 of 609 postings) | 4 | 5 |

##### Federal

- Share of federal postings from the top 4 employers: 100.0% (5 of 5 postings)
- Share of distinct federal roles from the top 4 employers by roles (their own ranking): 100.0% (5 of 5 roles)
- Federal postings that repeat a role already counted: 0.0% (0 of 5 postings with a company)

_(chart top-employers-federal.png not committed: Bars: the top federal employers' share of postings)_

Postings with no company are never an employer; they stay in the denominator. Concentration counts postings, not hires. Distinct titles and locations are from `v_employer_roles`: many postings with few titles means the same role reposted.

| Rank | Employer | Postings (share of the market) | Distinct titles | Locations |
|---|---|---|---|---|
| #1 | Department of Veterans Affairs | 40.0% (2 of 5 postings) | 2 | 2 |
| #2 | Department of Defense | 20.0% (1 of 5 postings) | 1 | 1 |
| #3 | Department of the Navy | 20.0% (1 of 5 postings) | 1 | 1 |
| #4 | General Services Administration | 20.0% (1 of 5 postings) | 1 | 0 |

#### 3. Employers with LCA filing history

Postings and employers whose employer matches DOL's LCA disclosure data for FY2024–FY2026 (`v_employer_sponsorship`, `last_3_fy`, on the normalized name). An employer without a match is **no match found**: the name may differ, or the employer may file under another entity. The levels count LCA **filings**, which are not approvals or hires.

From `v_employer_sponsorship_match`; levels are nested. 26 LCA filings loaded in all.

| Employer has | Commercial postings | Commercial employers | Federal postings | Federal employers |
|---|---|---|---|---|
| an LCA filing of any status in the window | 1.1% (7 of 609 postings) | 30.0% (6 of 20 employers) | 0.0% (0 of 5 postings) | 0.0% (0 of 4 employers) |
| ≥ 1 certified H-1B LCA filing | 1.0% (6 of 609 postings) | 25.0% (5 of 20 employers) | 0.0% (0 of 5 postings) | 0.0% (0 of 4 employers) |
| ≥ 1 certified analytics-SOC H-1B LCA filing | 0.8% (5 of 609 postings) | 20.0% (4 of 20 employers) | 0.0% (0 of 5 postings) | 0.0% (0 of 4 employers) |
| no match found | 98.9% (602 of 609 postings) | 70.0% (14 of 20 employers) | 100.0% (5 of 5 postings) | 100.0% (4 of 4 employers) |

#### 5. Offered wage on matched employers' analytics-SOC LCA filings

The wage employers **offered on their LCA filings** for analytics SOC codes, pooled over the filings of employers that post in each market. It describes filings, never what the postings pay, and the biggest filers dominate it.

From `v_matched_employer_lca_wages`. Median and IQR, never the mean.

| Market | Filings | Offered annual wage on LCA filings | Largest single filer's share | Note |
|---|---|---|---|---|
| commercial | 8 certified analytics-SOC H-1B LCA filings | $90,000 (IQR $79,030–$105,250; n=8 LCA filings from 4 employer(s)) | 50.0% (4 of 8 filings) | directional: under 15 filings or 5 employers |
| federal | 0 certified analytics-SOC H-1B LCA filings | n/a (0 LCA filings with a convertible wage) | n/a (0 of 0 filings) |  |

Robustness checks on the pooled median above. If they differ a lot from it, the pooled figure mostly reflects the largest filers. The first check needs at least 2 employers.

| Robustness check | Commercial | Federal |
|---|---|---|
| Pooled median without the single largest filer (n = LCA filings) | $83,500 (n=4) | n/a (n=0) |
| Median of each employer's median (n = employers) | $92,250 (n=4) | n/a (n=0) |

#### Methods and caveats (excerpt: the new lines)

- Distinct roles (`v_employer_roles`): a role is an (employer, normalized title) pair; postings with no company have none. It's a sensitivity measure, not a dedup: identical titles at one employer can be different jobs (roles undercount), and small wording variants count separately (roles overcount). The role share ranks employers by roles, so its top 10 can differ from the postings table; repeats are postings with a company minus their roles.
- **Federal LCA matches rarely bear on federal analyst jobs.** Federal civil-service positions generally require US citizenship, so an agency's LCA filings say little about its analyst postings. For the federal market the closed share, from the postings' own words, is the more relevant number.
- Federal postings in the closed bucket: 60.0% (3 of 5 postings)

##### LCA coverage of the filing window

How complete each fiscal year in the window is (`v_lca_coverage`, `v_lca_monthly`). A partial year holds fewer filings than a full one, so the window is uneven and year-to-year comparisons aren't like for like.

- FY2024: 4 of 12 months with decisions, 2024-04-06 to 2024-07-26; 4 LCA filings loaded (**partial fiscal year**: fewer than 12 months)
- FY2025: 5 of 12 months with decisions, 2024-10-07 to 2025-05-11; 8 LCA filings loaded (**partial fiscal year**: fewer than 12 months)
- FY2026: 9 of 12 months with decisions, 2025-10-04 to 2026-07-30; 14 LCA filings loaded (**partial fiscal year**: fewer than 12 months)

</details>

<details>
<summary>Report 4, what-postings-pay, rendered in full (synthetic demo data)</summary>

<!-- Generated by `python -m src.reports what-postings-pay`. Every table, chart and number is recomputed from the SQL views on each run, and the file is overwritten: write narrative in a copy (docs/reports.md). -->

> **Synthetic demo data, not market findings.**

### What commercial data-analyst postings pay

_Phase 5 report 4, regenerating Phase 3 Investigation #1. What commercial (Adzuna) data-analyst postings pay, from employer-disclosed salaries, with Adzuna's predicted salaries only as a labelled comparison._

| Provenance | |
|---|---|
| Database | `jobmarket_demo` |
| Generated at | 2026-10-29 04:00:22 UTC |
| Git commit | `94d0e1fbc2f9` |
| Rows in `v_commercial_salary_clean` | 302 |
| Rows in `v_ingestion_daily` | 52 |
| Rows in `v_salary_population` | 3 |
| Rows in `v_salary_skill_coverage` | 2 |

#### Headline

> **[TO WRITE: Headline]** One or two sentences on what employer-disclosed commercial postings pay. The employer-disclosed median is the only salary figure to quote here.
>
> Numbers from this run to draw on:
> - Employer-disclosed salary midpoint: $90,000 (IQR $75,000–$105,000; n=162, employer-disclosed)
> - Commercial postings with an employer-disclosed salary: 26.6% (162 of 609 postings)
> - Commercial postings in the clean salary population: 49.6% (302 of 609 postings)

#### 1. Who is measured

Every commercial (Adzuna) posting, narrowed to the clean salary population (`salary_quality = 'ok'`, USD, a yearly figure). Adzuna returns a salary for nearly every posting because its model fills in the ones employers didn't disclose, so **"salary present" is API behaviour, not a market fact**. The employer-disclosed share is the market fact.

From `v_salary_population`. Exclusions and the clean total are shares of every commercial posting; the clean split is a share of the clean population.

| Population | Postings |
|---|---|
| All commercial postings | 609 |
| With a salary figure of any kind (API behaviour) | 49.6% (302 of 609 postings) |
| With an employer-disclosed salary figure (the market fact) | 26.6% (162 of 609 postings) |
| Excluded: no salary figure | 50.4% (307 of 609 postings) |
| Clean salary population | 49.6% (302 of 609 postings) |
| Clean: employer-disclosed | 53.6% (162 of 302 clean postings) |
| Clean: Adzuna-predicted | 46.4% (140 of 302 clean postings) |

#### 2. The disclosed anchor

The salary midpoint employers disclosed themselves: the only salary figure in the headline.

- Employer-disclosed salary midpoint: $90,000 (IQR $75,000–$105,000; n=162, employer-disclosed)

#### 3. Predicted vs disclosed, as a comparison

Adzuna's predicted salaries are **its own model's estimate, not a market observation**. They are summarized separately and compared with the disclosed figure; the two are never pooled into one number.

From `v_commercial_salary_clean`, one basis per row.

| Basis | Salary midpoint |
|---|---|
| employer-disclosed | $90,000 (IQR $75,000–$105,000; n=162, employer-disclosed) |
| Adzuna-predicted | $90,000 (IQR $80,000–$100,000; n=140, Adzuna-predicted) |

- Adzuna-predicted minus employer-disclosed: +$0 (Adzuna-predicted $90,000, n=140 vs employer-disclosed $90,000, n=162)

_(chart disclosed-vs-predicted.png, not committed: two boxes, employer-disclosed and Adzuna-predicted salary midpoints)_

#### 4. Disclosed by seniority

Seniority comes from the **job title only** (`src/cleaning/seniority.py`), so it is instrument-limited: a level stated only in the description is invisible. **No title signal** is its own row, never folded into mid.

Employer-disclosed postings only. A group under n ≥ 15 shows its n; its median is withheld.

| Seniority | Postings (share of disclosed) | Salary midpoint |
|---|---|---|
| junior | 7.4% (12 of 162 postings) | withheld: n=12 is under the n ≥ 15 floor (employer-disclosed) |
| mid | 7.4% (12 of 162 postings) | withheld: n=12 is under the n ≥ 15 floor (employer-disclosed) |
| senior | 19.1% (31 of 162 postings) | $85,000 (IQR $75,000–$110,000; n=31, employer-disclosed) |
| no title signal | 66.0% (107 of 162 postings) | $80,000 (IQR $70,000–$100,000; n=107, employer-disclosed) |

_(chart disclosed-by-seniority.png, not committed: boxes of employer-disclosed salary midpoints by seniority)_

#### 5. Disclosed by metro

Metro is a lookup against a curated list of tracked metros (8 cities plus DC, `src/cleaning/metro.py`), never a default. A posting anywhere else, or with an unparsed location, is **not on the tracked metro list**: that row describes the list, not a market.

Employer-disclosed postings only. A group under n ≥ 15 shows its n; its median is withheld.

| Metro | Postings (share of disclosed) | Salary midpoint |
|---|---|---|
| Chicago | 19.1% (31 of 162 postings) | $90,000 (IQR $80,000–$90,000; n=31, employer-disclosed) |
| NYC | 16.0% (26 of 162 postings) | $108,750 (IQR $75,000–$110,000; n=26, employer-disclosed) |
| Austin | 14.8% (24 of 162 postings) | $92,500 (IQR $76,250–$107,500; n=24, employer-disclosed) |
| SF Bay Area | 14.8% (24 of 162 postings) | $82,500 (IQR $75,000–$95,000; n=24, employer-disclosed) |
| Boston | 8.0% (13 of 162 postings) | withheld: n=13 is under the n ≥ 15 floor (employer-disclosed) |
| DC | 4.9% (8 of 162 postings) | withheld: n=8 is under the n ≥ 15 floor (employer-disclosed) |
| Seattle | 3.7% (6 of 162 postings) | withheld: n=6 is under the n ≥ 15 floor (employer-disclosed) |
| not on the tracked metro list | 18.5% (30 of 162 postings) | $90,000 (IQR $80,000–$100,000; n=30, employer-disclosed) |

#### 6. Why there are no skill premiums here

From `v_salary_skill_coverage` (tags at confidence ≥ 0.8).

| Basis | Clean postings | With any skill tag (truncation-floored) | Largest single-skill n | Skills at n ≥ 15 |
|---|---|---|---|---|
| employer-disclosed | 162 | 100.0% (162 of 162 jobs) | 78 | 9 |
| Adzuna-predicted | 140 | 100.0% (140 of 140 jobs) | 74 | 10 |

A skill premium isn't computed. The three reasons, checked against this data:

- **Disclosed tags:** on this data 9 skill(s) reach n ≥ 15 among employer-disclosed postings, so this reason doesn't hold here; the other two still do, and no premium is computed.
- **The text is truncation-floored:** Adzuna cuts descriptions at about 500 characters, so tags undercount, and unevenly.
- **Pooling predicted salaries would make any premium partly Adzuna's own model,** not what employers pay.

What would unblock it: [docs/findings_skill_premium_deferred.md](../../docs/findings_skill_premium_deferred.md).

#### 7. Over time

- Distinct commercial snapshot days so far (2026-10-02 to 2026-10-29): 26

Salary trends wait for history: this report computes no trend, and every figure above covers all the postings seen so far.

#### What it means

> **[TO WRITE: What it means]** What the disclosed figure says about analyst pay, how far predicted salaries differ, and what the measurement can't show (who discloses, title-only seniority, the metro list).
>
> Numbers from this run to draw on:
> - Adzuna-predicted salary midpoint (a model estimate, for comparison): $90,000 (IQR $80,000–$100,000; n=140, Adzuna-predicted)
> - Adzuna-predicted minus employer-disclosed: +$0 (Adzuna-predicted $90,000, n=140 vs employer-disclosed $90,000, n=162)
> - Commercial postings with a salary figure of any kind: 49.6% (302 of 609 postings)
> - Employer-disclosed, seniority senior: $85,000 (IQR $75,000–$110,000; n=31, employer-disclosed)
> - Employer-disclosed, seniority no title signal: $80,000 (IQR $70,000–$100,000; n=107, employer-disclosed)
> - employer-disclosed: postings with any skill tag (truncation-floored): 100.0% (162 of 162 jobs)
> - Adzuna-predicted: postings with any skill tag (truncation-floored): 100.0% (140 of 140 jobs)
> - (commercial skill rates are truncation-floored)

#### What to do about it

> **[TO WRITE: What to do about it]** What a job seeker should take from this, at aggregate level: a range to expect, never a promise about one posting.
>
> Numbers from this run to draw on:
> - Employer-disclosed, metro Chicago: $90,000 (IQR $80,000–$90,000; n=31, employer-disclosed)
> - Employer-disclosed, metro NYC: $108,750 (IQR $75,000–$110,000; n=26, employer-disclosed)
> - Employer-disclosed, metro Austin: $92,500 (IQR $76,250–$107,500; n=24, employer-disclosed)
> - Employer-disclosed, metro SF Bay Area: $82,500 (IQR $75,000–$95,000; n=24, employer-disclosed)
> - Employer-disclosed, metro not on the tracked metro list: $90,000 (IQR $80,000–$100,000; n=30, employer-disclosed)
> - Metros clearing the n ≥ 15 floor: 5
> - Distinct snapshot days so far: 26

#### Methods and caveats

- Population: commercial (Adzuna) postings with `salary_quality = 'ok'`, `salary_currency = 'USD'` and `salary_period = 'year'` (`v_commercial_salary_clean`).
- Each posting's salary is its midpoint, (salary_min + salary_max) / 2.
- Salaries are summarized by the median and the interquartile range, never the mean: salaries are right-skewed, so a few very high ones pull a mean up.
- IQR: the 25th to 75th percentile, linear interpolation (as Postgres's percentile_cont).
- Predicted vs disclosed: `salary_is_predicted` separates Adzuna's model estimates from employer-disclosed figures. They are summarized separately and never pooled.
- Floor: a group under n ≥ 15 shows its n, but its median is withheld.
- Seniority comes from the title only; metro from a curated list of tracked metros; Adzuna's text is truncated at about 500 characters.
- Federal postings are excluded: GS pay bands aren't comparable with commercial salaries, and federal pay is disclosed by law, so there is no disclosure selection to compare.
- Who discloses: Phase 3 found that employer-disclosed salaries skew toward compensation-forward posting text and disclosure-law metros, which partially explains why they differ from predicted ones; a residual is unexplained. That is a hypothesis, not a proven cause.
- Commercial postings read: 609

</details>

<details>
<summary><code>python -m src.doctor</code> on the demo database (synthetic demo data)</summary>

Run with `DATABASE_URL` pointing at `jobmarket_demo` and FAKE values in the four source variables (no `.env` in this VM).

```text
Job Market Tracker doctor (read-only: it changes nothing)
  PASS  1 .env: no .env file; DATABASE_URL comes from the environment; DATABASE_URL uses postgresql+psycopg2://; set: ADZUNA_APP_ID, ADZUNA_APP_KEY, USAJOBS_API_KEY, USAJOBS_USER_AGENT_EMAIL
  PASS  2 database: reachable at 127.0.0.1:5432
  PASS  3 migrations: at head a02471448340
  PASS  4 views: all 22 views exist
  WARN  5 daily clock: H1 adzuna PASS; H1 usajobs PASS; H2 PASS; H7 WARN (1 day(s) without a snapshot in the last 14 days: 2026-10-20); streak 9 of 60 consecutive days; snapshot days 27 of 90
            fix:   Start-ScheduledTask -TaskName JobMarketTracker-Daily   # then see docs\daily-operation.md, "If a day was missed"
            posix: ./scripts/run_daily.sh   # then see docs/daily-operation.md, "If a day was missed"
  SKIP  6 scheduled task: not Windows (on Linux, cron runs scripts/run_daily.sh)
  WARN  7 LCA data: FY2024: 4 cases, 4 months (2024-04-06 to 2024-07-26); FY2025: 8 cases, 5 months (2024-10-07 to 2025-05-11); FY2026: 14 cases, 9 months (2025-10-04 to 2026-07-30). FY2024 has 4 of 12 months (missing 2023-10, 2023-11, 2023-12, 2024-01, 2024-02, 2024-03, 2024-08, 2024-09); FY2025 has 5 of 12 months (missing 2025-02, 2025-03, 2025-04, 2025-06, 2025-07, 2025-08, 2025-09)
            fix:   follow src\visa\README.md, steps 1-3: download into data\lca\, then load
            posix: follow src/visa/README.md, steps 1-3
  PASS  8 file placement: no untracked .xlsx, .csv, .dump or .log outside data/, logs/
  PASS  9 virtualenv: no other virtualenv active
  PASS 10 uv.lock: no uv.lock
overall WARN: 0 FAIL, 2 WARN; exit code 0
```

Check 5 WARNs because the demo seeds one deliberately missing day, which H7 lists. Check 7 WARNs because the demo's LCA rows span only a few months per fiscal year. Check 6 SKIPs off Windows. Every other check PASSes, and the exit code is 0.

</details>

## Parked questions

| Q | Part | Question | Recommendation |
|---|---|---|---|
| 1 | A | The default `--db-wait` | (a) keep 300 s |
| 2 | A | A second daily trigger when a run exits 2 | (b) add one at 13:15 that does nothing if today already has a snapshot |
| 3 | A | Auto-start Docker Desktop from `run_daily.ps1` | (a) no |
| 4 | A | H7's window and today's exclusion | (a) keep 14 days, today excluded |
| 5 | B | A doctor `--fix` for safe fixes | (a) no: print commands only |
| 6 | B | Should the daily runner run the doctor's checks first? | (a) no |
| 7 | B | Should a daily-clock FAIL (H1/H2) fail the doctor? | (a) yes, as built |
| 8 | B | `uv.lock`: commit it? | (a) leave it untracked until the server image needs pinned versions |
| 9 | C | Make the distinct-role share the primary concentration number? | (a) no: both shown, postings first |
| 10 | C | The sparse-month threshold | (a) keep 10% of the FY's median month |
| 11 | C | Hide the federal match rows entirely? | (a) no: show them, with the note |
| 12 | C | A second chart for roles | (a) no |
| 13 | C | "Largest filer": by filings, ties to the first key | (a) keep |
| 14 | D | The salary floor, and a "directional" median for n 5–14 | (a) keep 15, no directional median |
| 15 | D | Mention the predicted median in the headline? | (a) no |
| 16 | D | The IQR method | (a) linear, like `percentile_cont` |
| 17 | D | Show min/max ranges as well as midpoints | (a) no, midpoints only |
| 18 | D | The day threshold for a salary trend section | (b) 90 snapshot days |
| 19 | D | Salary and distinct-role cards in Metabase | (b) after the reports' narrative is written |
| 20 | D | Over time: commercial snapshot days only | (a) keep |
| 21 | E | The default direction | (a) longer key onto the shorter one |
| 22 | E | Should `--write` also run the follow-up commands? | (a) no: print them |
| 23 | E | A key other aliases point at | (a) refuse, as built |
| 24 | E | Commit the owner's `company_aliases.json` additions? | (a) yes, after the re-render looks right |
| 25 | F | Should roles ever become primary in Report 1? | (a) no |
| 26 | F | The roles unit: category presence or skill tags | (a) category presence, as built |

### Q1. The default `--db-wait`
- **What I found:** after a login or wake, Docker Desktop typically needs a minute or two before the engine answers.
- **Options:** (a) 300 s; (b) 600 s; (c) 120 s.
- **Recommendation:** (a). It covers a slow start without holding the task for long: the task's own limit is an hour.

### Q2. A second daily trigger
- **What I found:** an exit 2 loses the day unless someone notices. Task Scheduler's restart-on-failure option reacts to a task that fails to start, not to a non-zero exit code.
- **Options:**
  - (a) No second trigger.
  - (b) A second trigger at 13:15 local that exits at once if today (UTC) already has a snapshot.
  - (c) Rely on the dead-man's switch.
- **Recommendation:** (b), with the guard, so a good morning run isn't repeated and no extra Adzuna calls are spent. Built: (a).

### Q3. Auto-start Docker Desktop
- **Options:** (a) no; (b) start `Docker Desktop.exe` from `run_daily.ps1` if it isn't running.
- **Recommendation:** (a). Docker Desktop's "Start when you sign in" setting is the supported switch, and a script launching a GUI app from a scheduled task is brittle.

### Q4. H7's window
- **What I found:** today is left out because the 07:15 run may not have happened yet, and H2 already covers today.
- **Options:** (a) 14 days, today excluded; (b) 30 days; (c) include today after 12:00 UTC.
- **Recommendation:** (a).

### Q5. A doctor `--fix`
- **Options:** (a) print commands only; (b) `--fix` for safe ones (apply views, start the db).
- **Recommendation:** (a) for now. Read-only makes it safe to run any time, and the fixes are one command each.

### Q6. Doctor checks before the daily run
- **Options:** (a) no; (b) run checks 1–4 first and stop on a FAIL.
- **Recommendation:** (a). The runner already waits for the database and runs health at the end. Missing views don't stop ingestion.

### Q7. A daily-clock FAIL fails the doctor
- **What I found:** on a fresh database, H2 FAILs ("no snapshots at all"), so the doctor exits 1.
- **Options:** (a) yes, as built; (b) report the clock as WARN at most.
- **Recommendation:** (a). A clock that never ran is the problem the doctor exists to surface.

### Q8. `uv.lock`
- **What I found:** the doctor reports an untracked `uv.lock` as INFO and gives no advice.
- **Options:** (a) leave it untracked; (b) commit it; (c) gitignore it.
- **Recommendation:** (a), and decide when the server's pipeline image needs pinned versions.

### Q9. The primary concentration number
- **Options:** (a) both, postings first; (b) roles first; (c) roles only.
- **Recommendation:** (a). Postings are what's measured. Roles are a sensitivity check with known undercount and overcount.

### Q10. The sparse-month threshold
- **Options:** (a) 10% of the FY's median month; (b) 25%; (c) a fixed count.
- **Recommendation:** (a). It flags an empty-looking month without flagging normal seasonality.

### Q11. Federal match rows
- **Options:** (a) show them, with the no-analytics note and the Methods caveat; (b) hide them.
- **Recommendation:** (a). Hiding a number invites the question of why; the note and the caveat say what it means.

### Q12. A roles chart
- **Options:** (a) none; (b) a second bar chart of roles.
- **Recommendation:** (a). Two near-identical bar charts of employers read worse than the table's extra columns.

### Q13. "Largest filer"
- **What I found:** the robustness median drops the employer with the most filings in the window, ties to the alphabetically first key, the same count as `largest_employer_n_filings`.
- **Options:** (a) keep; (b) rank by filings with a wage.
- **Recommendation:** (a).

### Q14. The salary floor
- **Options:** (a) 15, withheld below; (b) 15, plus a labelled "directional" median for n 5–14; (c) 10.
- **Recommendation:** (a). It's Investigation #1's bar, and a directional median tends to get quoted without its label.

### Q15. The predicted median in the headline
- **Options:** (a) no; (b) as a labelled comparison.
- **Recommendation:** (a). Section 3 is where it's compared.

### Q16. The IQR method
- **Options:** (a) linear interpolation, like `percentile_cont`; (b) nearest rank.
- **Recommendation:** (a): it matches the views.

### Q17. Min/max ranges
- **Options:** (a) midpoints only; (b) also the ranges' spread.
- **Recommendation:** (a) until the narrative needs it.

### Q18. A salary trend section
- **Options:** (a) never; (b) once there are 90 snapshot days; (c) 30 days.
- **Recommendation:** (b): the project's own target. Built: no trend at all.

### Q19. Metabase cards
- **Options:** (a) none; (b) salary and distinct-role cards after the reports' narrative; (c) now.
- **Recommendation:** (b). Dashboards were out of scope here.

### Q20. Snapshot days in Report 4
- **What I found:** section 7 counts commercial (Adzuna) snapshot days, since the report is about commercial postings.
- **Options:** (a) commercial only; (b) every source.
- **Recommendation:** (a).

### Q21. The alias direction
- **Options:** (a) longer onto shorter, alphabetical tie-break; (b) always keep the company key; (c) always keep the LCA key.
- **Recommendation:** (a). Override it per row with the keep columns.

### Q22. `--write` running the follow-ups
- **Options:** (a) print them; (b) run them.
- **Recommendation:** (a). Each step is visible and can be run one at a time.

### Q23. Chains on the source side
- **What I found:** mapping a key that other aliases already point at would leave those aliases one step short, because the normalizer applies the map once.
- **Options:** (a) refuse, suggesting the keep column; (b) re-point the existing aliases automatically.
- **Recommendation:** (a). It never rewrites an existing entry.

### Q24. Committing alias additions
- **What I found:** `company_aliases.json` is tracked, and it already holds company names. It carries no sponsorship data.
- **Options:** (a) commit after the re-render looks right; (b) keep the additions local.
- **Recommendation:** (a). The runbook leaves this to you.

### Q25. Roles as primary in Report 1
- **Options:** (a) never; (b) once titles are deduplicated more carefully.
- **Recommendation:** (a): it stays a sensitivity check.

### Q26. The roles unit
- **What I found:** the brief defines a role as carrying a category if any posting has it, so the roles column counts role-category pairs while the postings column counts skill tags. The caption says to compare rankings, not points.
- **Options:** (a) category presence; (b) distinct (role, skill) tags.
- **Recommendation:** (a), as built. (b) is the change to make if you want like-for-like units.

## What you run on the laptop after merging (Windows PowerShell)

One command at a time:

```powershell
git checkout main
git pull
uv sync
uv run alembic upgrade head
uv run python scripts/apply_views.py
```

`apply_views.py` should end with **`22 views applied`**.

```powershell
docker compose up -d db
```

Compose recreates the `db` container with the new restart policy. Your data stays in the `jobmarket_pg_data` volume.

```powershell
uv run python -m src.doctor
```

**A healthy result** ends with `exit code 0`:
- Checks 1–4 PASS.
- 5 is PASS, or WARN only before today's 07:15 run.
- 6 PASSes with last result 0 (267011 if the task hasn't run since it was registered).
- 7 PASSes, now that FY2024 and FY2025 have 12 months each. The current FY is partial, and that's fine.
- 8–10 PASS or INFO.

Any FAIL line ends with the command that fixes it.

Re-render all four reports (this loop stops at the first failure):

```powershell
foreach ($r in @("commercial-vs-federal-skills", "how-much-employers-disclose", "employers-and-sponsorship", "what-postings-pay")) {
  uv run python -m src.reports $r
  if ($LASTEXITCODE -ne 0) { Write-Host "STOP: $r"; break }
}
```

Review the match candidates with the new helper: mark `approved` with `y` in Excel, save as CSV, then run these one at a time:

```powershell
uv run python -m src.visa.sponsor_match
uv run python -m src.cleaning.aliases apply --from "data\sponsor_match_candidates.csv"
uv run python -m src.cleaning.aliases apply --from "data\sponsor_match_candidates.csv" --write
uv run python -m src.cleaning.apply_cleaning --only companies
uv run python -m src.visa.lca_loader --rekey
uv run python scripts/apply_views.py
uv run python -m src.reports employers-and-sponsorship
```

Do the same for `data\company_merge_candidates.csv`. Read the dry run's refused rows before `--write`.

**What to look at first:**

- **Report 3, section 2:**
  - Compare the share of postings from the top 10 with the share of distinct roles, and read the "repeat a role already counted" line. The Distinct titles and Locations columns show which employers repost.
  - Cross-check: the repeat count equals postings with a company minus `sum(n_roles)` in `v_employer_roles`.
- **Report 3, section 3:** under the match table, the federal note ("include no analytics-SOC H-1B filings") should appear. Methods should show the federal closed share.
- **Report 3, Methods, "LCA coverage of the filing window":** FY2024 and FY2025 should show 12 of 12 months, and FY2026 nine, flagged partial. October 2025 should be flagged as a month with unusually few decisions.
- **Report 3, section 5:** compare the two robustness rows with the pooled median. A big gap means the pooled figure is mostly the largest filer.
- **Report 4:**
  - Section 1's clean total should equal:
    ```powershell
    docker compose exec -T db psql -U postgres -d jobmarket -c "select count(*) from v_commercial_salary_clean"
    ```
  - Section 2's n should equal the same count `where not salary_is_predicted`.
  - Compare sections 2–4 with Investigation #1 in `docs/phase_3_findings.md` for consistency.
  - Seniority groups under n ≥ 15 show only their n.

## Surprises

- **pwsh couldn't run here.** The apt package doesn't exist, and running the downloaded release was blocked by this session's permission policy, so the `.ps1` files weren't parse-checked. Static tests stand in. Running `.\scripts\windows\run_daily.ps1 --dry-run --skip adzuna usajobs` once on the laptop would confirm it parses.
- **The local `main` ref was stale** and pointed at an old commit. The first real-figure grep against it matched figures from earlier, already-merged docs. With `main` pointed at `origin/main` (locally; nothing pushed to main) the grep prints nothing.
- **On the demo database the doctor WARNs twice by design:** the demo has a deliberately missing day (H7) and only a few LCA months per FY.
- **The demo tags every clean posting,** so on the demo the disclosed basis reaches the skill floor, and Report 4's first "why no premiums" reason flips. That text is data-aware: it says the reason doesn't hold on this data, and still computes no premiums.
- **Report 4 reads a row-level view.** `v_commercial_salary_clean` carries `job_id` and `title`. The report uses it only for medians, and a test checks that no title or job id reaches the output.
- **The README said "sixteen SQL views"** when main had 17. It now says twenty-two.
- **C1 changed no golden file:** every 100.0% in them was an exact whole.
- **Two existing health tests changed for H7.** One seeded a deliberate gap and asserted every check PASSes.
- **Coincidence in a test fixture:** the invented senior median equalled the pooled median twice. The never-pooled test now compares the anchor section directly.

## Suggested PR title

**Overnight batch: daily clock hardening, laptop doctor, Report 3 improvements, Report 4 (salaries), alias helper, Report 1 roles sensitivity**

<details>
<summary>PR description (ready to paste)</summary>

## Summary

An overnight batch in six parts, each in small commits that stand on their own. Everything is tested on synthetic data only.

**A. Keep the daily clock running**
- `docker-compose.yml`: `restart: unless-stopped` on `db`.
- The daily runner waits for the database (`--db-wait`, default 300 s; host:port logged, never the password). If the database never comes up it prints a clear message and a summary with a `db` FAIL line, sends the failure ping, and exits **2**.
- `run_daily.ps1` / `run_daily.sh` run `docker compose up -d db` first.
- Health check **H7** lists the days in the last 14 with no snapshot.
- docs/daily-operation.md: exit codes, after a reboot or wake, how to tell the clock is running, missed days.

**B. The laptop doctor**
- `python -m src.doctor` (`make doctor`, `--json`): ten read-only checks, each with the exact PowerShell fix.
  - `.env`, including NUL bytes
  - database, migrations, views
  - the daily clock and the scheduled task
  - LCA coverage
  - files in the wrong place
  - VIRTUAL_ENV and `uv.lock`
- `docs/laptop-runbook.md`: after every pull, weekly, and a troubleshooting table.

**C. Report 3 (employers-and-sponsorship)**
- Small rates render `<0.1%` / `>99.9%` everywhere.
- `v_employer_roles`: distinct titles and locations beside postings, the top-10 share of distinct roles, and the share of postings that repeat a role.
- Federal framing: a note when matched employers have no analytics-SOC filings, and a citizenship caveat with the closed share.
- `v_lca_monthly` and an LCA coverage block in Methods, flagging partial fiscal years and sparse months.
- Wage robustness: the median without the largest filer and the median of employer medians (columns appended at the end of `v_matched_employer_lca_wages`).

**D. Report 4, `what-postings-pay`** (Phase 3 Investigation #1, regenerated)
- Salary guardrails: `SALARY_FLOOR = 15`, `FlooredSalary`, `SalaryDiff`, and a no-"mean" wording check.
- `v_salary_population` and `v_salary_skill_coverage`.
- The report:
  - who is measured
  - the disclosed anchor
  - predicted vs disclosed, as a comparison with two separately drawn boxes
  - disclosed by seniority and by metro, with the floor
  - why there are no skill premiums
  - snapshot days
  - generated Methods
  - `[TO WRITE]` placeholders

**E. Alias helper**
- `python -m src.cleaning.aliases apply --from <csv> [--write]` promotes approved match-review pairs into `company_aliases.json`.
- It validates every pair: normalized keys; no self-map, conflict, chain or cycle.
- Dry run by default, with a JSON diff. Running it twice adds nothing.
- The file's format and comments are kept.

**F. (stretch) Report 1 sensitivity:** `v_skill_category_composition_roles`, and a "Sensitivity: distinct roles" table. The primary numbers are unchanged.

## Testing

- `pytest` with `TEST_DATABASE_URL`: 577 → **693 passed**, 1 skipped (the Metabase e2e).
- `ruff check .` / `ruff format --check .` (0.17.2) clean; the alembic round trip is clean (no migration); `make views` applies **22** views, twice; `shellcheck scripts/run_daily.sh` clean.
- Goldens: Report 3 and Report 1 updated (diffs reviewed), Report 4 new, Report 2 unchanged.
- Demo end-to-end runs for Reports 1, 3 and 4 and for the doctor.
- `.ps1` files: checked statically (ASCII only, docker before Python, exit code); pwsh wasn't available to parse-check them.
- Synthetic data only. No job or government site called, no ingestion. No data, logs, rendered output, `.env`, `uv.lock` or `company_aliases.json` change; the real-figure grep prints nothing.

## Open questions

26 parked decisions, each with the default that was built, are in `docs/overnight-batch.md`. Among them:
- the `--db-wait` default, and a second daily trigger after an exit 2
- a doctor `--fix`
- which concentration number is primary
- the sparse-month and salary floors
- the alias direction, and committing alias additions

## After merging

`docs/overnight-batch.md` has the laptop steps:
- `uv sync`, `alembic upgrade head`, `apply_views.py` (22 views)
- `docker compose up -d db` (applies the restart policy, keeps the data)
- the doctor
- re-render all four reports
- the alias helper

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01ATh4ABgiML8G58MzgJ36ZP

</details>
