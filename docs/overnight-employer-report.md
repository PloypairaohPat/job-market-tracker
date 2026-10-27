# Overnight run: Report 3, who hires data analysts and who has filed to sponsor them, on demo data (Milestone F)

## Report

- **Branch:** `claude/employer-report`, off `main` at `b1fde13` ("Merge pull request #5 from PloypairaohPat/claude/report-kit"). This session's setup named a different working branch; per the brief, everything went to `claude/employer-report`.
- **Commits on top of main `b1fde13`:** 5, plus this report (listed below). **Pushed:** yes, after every green commit. No force push, nothing to `main`, no PR.
- **STOP conditions:** none held.
  - `b1fde13` is in main's history.
  - The baseline on clean main was green: **518 passed, 1 skipped**.
  - `alembic heads` showed one head, `a02471448340`.
  - `src/reports/catalog.py` listed exactly the two existing reports (`skill_demand`, `disclosure`).
- **Verification setup:**
  - Local Postgres 16 on 127.0.0.1, with a freshly recreated `jobmarket_test` before every commit.
  - A gate script that **exits on the first failure**: pytest with `TEST_DATABASE_URL`, `ruff check .`, `ruff format --check .` (0.17.2), the alembic upgrade → downgrade → upgrade round trip on a recreated database, and `make views` twice. It stopped one commit at `ruff format`; I fixed the formatting and re-ran the whole gate.
  - Versions: Python 3.13.17, SQLAlchemy 2.1.6, alembic 1.20.1, pandas 3.1.0, matplotlib 3.11.2, pytest 9.1.1, ruff 0.17.2.
- **Data:** synthetic only, from `seed_demo_data.py --full` (guard untouched) into local `jobmarket_demo` and `jobmarket_test`. Its LCA rows are the seed's own FAKE employers. No LCA file was downloaded or loaded, no job or government API was called, and no ingestion ran.
- **Charts:** I looked at every chart before committing (the two top-employer bar charts on the demo data).
- **Compare:** https://github.com/PloypairaohPat/job-market-tracker/compare/main...claude/employer-report?expand=1

| Check | Baseline (clean main) | Final |
|---|---|---|
| `pytest` with `TEST_DATABASE_URL` | 518 passed, 0 failed, 1 skipped | **553 passed, 0 failed, 1 skipped** (+35: LCA guardrails 20, new views 7, report 3 8). The skip is the Metabase e2e test, which needs `METABASE_URL` |
| `ruff check .` (0.17.2) | clean | clean |
| `ruff format --check .` (0.17.2) | clean | clean, 132 files |
| alembic upgrade → downgrade → upgrade on a recreated database | clean | clean (no migration in this milestone) |
| `make views` on a fresh database, twice | 12 views | **16 views**, twice |
| Golden file (report 3 from hand-built frames, FAKE names, invented numbers) | — | matches `tests/fixtures/reports/employers-and-sponsorship.md` |
| End to end on the full demo seed, with LCA data | — | renders; provenance row counts equal `count(*)` of each view; no `nan`/`None`; no URL |
| Same, after `truncate lca_cases` | — | renders; the three sponsorship sections say "LCA data not loaded"; hiring sections intact |
| New views cross-checked on the demo seed | — | postings agree with `v_market_jobs`; bucket counts with `v_job_visa_outlook`; the filing count with `v_employer_sponsorship.certified_h1b_analytics_soc` |
| GitHub Actions CI on the branch | — | **#41–#43 green** (test 3.11, test 3.12, image); #44 (README only) was still running when this was written |

## What shipped

| # | Commit | What |
|---|---|---|
| 1 | `81f1585` | LCA guardrails (`src/reports/lca_guardrails.py`) |
| 2 | `7db0afc` | Four aggregate views for report 3 |
| 3 | `66b0438` | Report 3, `employers-and-sponsorship`; `largest_employer_n_filings`; catalog; golden and end-to-end tests; `docs/reports.md` row |
| 4 | `0e07399` | README: three reports in the kit, view count |
| 5 | (this) | This report |

**1. LCA guardrails.** `src/visa/README.md`'s "What this can't tell you", as code:

| Code | Enforces |
|---|---|
| `FilingCount` | Must say it counts LCA filings. Refuses labels with "hires", "hired", "hiring", "approved", "approvals", "granted" or "visas". |
| `FilingWage` | Median and IQR of the offered wage on LCA filings, with the filing and employer counts behind it. No mean, and nothing calls it what postings pay. |
| `check_sponsorship_text` | Runs on every rendered report 3. Refuses claims the data can't support: "doesn't sponsor", "do not sponsor", "never files", "non-sponsoring", "no sponsorship history", "H-1B hires", "LCA approvals". An unmatched employer is "no match found". |
| `BUCKET_LABELS` | Read "unknown (no signal; never a "no")" and "strong (not a "yes")". |
| `LCA_CAVEATS` + `check_caveats` | The report must print the five required caveats in Methods: filing not hire, large filers, unknown not no, truncated text, cap-exempt hint. E-Verify and rules change are printed too. |
| `check_aggregate` | Refuses any view frame with a job id, title, URL, description or case number. |

**2. Views** (all aggregate, one row or more per market, populations defined inline because they sort before `v_market_jobs`):

- `v_employer_postings`: postings per (market, employer), with the market's posting and employer totals. No-company postings form one row that counts in the total but is never an employer.
- `v_employer_sponsorship_match`: per market, postings and employers matched to `v_employer_sponsorship` (`last_3_fy`), at three nested levels:
  - any LCA filing
  - ≥ 1 certified H-1B
  - ≥ 1 certified analytics-SOC H-1B

  It also carries the denominators, `lca_rows_loaded` (0 = not loaded) and the FY window.
- `v_visa_outlook_summary`: `v_job_visa_outlook` counted per (market, bucket, reason). The report never loads the per-job view behind the private dashboard.
- `v_matched_employer_lca_wages`: the offered annual wage on matched employers' certified analytics-SOC H-1B filings. It holds p25/median/p75, `n_filings`, `n_filings_with_wage`, `n_employers`, `n_employers_with_wage`, and the largest single filer's filing count (no name).
  - It repeats `v_employer_sponsorship`'s SOC list, certified rule, window and annualization unchanged, and a test pins the copied SQL to the original.
  - It exists because `v_employer_sponsorship.median_offered_annual_wage` is per employer and covers every SOC, with no IQR or n, and a median of medians would be wrong.

Tests cover hand-built rows, no LCA data, and demo cross-checks:
- the hand-built rows include Certified-Withdrawn, E-3, out-of-window and hourly filings, plus no-company and out-of-scope postings
- no new view carries a row-level column

**3. Report 3** (`python -m src.reports employers-and-sponsorship`), per market, never pooled:

1. **Who is compared:** postings, employers posting, postings with no company.
2. **Who posts analyst jobs:**
   - the top 10 employers by postings, as a chart and a table, each with its share of the market
   - the top 10's combined share, with its denominator
   - a note when employers tie at the cutoff
3. **Employers with LCA filing history:**
   - the three nested levels, for postings and employers, plus a "no match found" row
   - the FY window and the number of filings loaded
4. **Visa outlook buckets, counts only:**
   - closed / strong / possible / unknown, as shares of in-scope postings
   - the share of closed driven by citizenship or clearance requirements
   - why closed and why unknown, by the rule that fired
5. **Offered wage on matched employers' analytics-SOC LCA filings:**
   - median + IQR with filings and employers
   - the largest single filer's share
   - a "directional" note under 15 filings or 5 employers
   - the count of filings without an annualizable wage

Then:
- headline, what it means, and what to do about it, as `[TO WRITE]` placeholders with this run's numbers
- Methods and caveats, including the full "What LCA data can't tell you" list

With `lca_cases` empty, sections 3–5 each say "**LCA data not loaded.**" and point to `src/visa/README.md` (steps 1–3); sections 1 and 2 render as usual.

**Privacy:**
- Employers are named only beside their posting counts. Every sponsorship number is an aggregate.
- No job titles, URLs or filing rows appear.
- A test checks that no employer name appears in the sponsorship sections.

On the demo, the top employers are real names with synthetic postings. Keeping sponsorship aggregate also keeps synthetic sponsorship data away from those names, as the demo seed's own rule requires.

## Sample: Report 3 rendered on demo data

This is `python -m src.reports employers-and-sponsorship` on the local `jobmarket_demo` at the final code commit. It's shown here only; no rendered output is committed. The data is synthetic: the LCA rows belong to the seed's FAKE employers, the federal market is 5 postings, and the numbers mean nothing.

The two charts aren't included. Each is a single-series horizontal bar chart of the top employers' shares, every bar labelled with its full rate, with the demo banner in the title.

<details>
<summary>Rendered report.md (demo data)</summary>

```markdown
<!-- Generated by `python -m src.reports employers-and-sponsorship`. Every table, chart and number is recomputed from the SQL views on each run, and the file is overwritten: write narrative in a copy (docs/reports.md). -->

> **Synthetic demo data, not market findings.**

# Who hires data analysts, and who has filed to sponsor them

_Phase 5 report 3. Who posts analyst jobs, how concentrated hiring is, and how many of those employers have filed LCAs for analytics roles. Aggregate and employer-level only: the per-job Visa outlook dashboard stays private._

| Provenance | |
|---|---|
| Database | `jobmarket_demo` |
| Generated at | 2026-10-27 03:16:57 UTC |
| Git commit | `0e07399b6297` |
| Rows in `v_employer_postings` | 25 |
| Rows in `v_employer_sponsorship_match` | 2 |
| Rows in `v_matched_employer_lca_wages` | 2 |
| Rows in `v_visa_outlook_summary` | 11 |

## Headline

> **[TO WRITE: Headline]** One or two sentences on who hires data analysts and how concentrated that is, and, separately, how many of those employers have a record of LCA filings.
>
> Numbers from this run to draw on:
> - Commercial postings: 609
> - Commercial employers posting: 20
> - Commercial share of postings from the top 10 employers: 83.7% (510 of 609 postings)
> - Federal postings: 5
> - Federal employers posting: 4
> - Federal share of postings from the top 4 employers: 100.0% (5 of 5 postings)
> - Commercial employers with ≥ 1 certified H-1B LCA filing: 25.0% (5 of 20 employers)
> - Federal employers with ≥ 1 certified H-1B LCA filing: 0.0% (0 of 4 employers)

## 1. Who is compared

**Commercial** is every Adzuna posting; **federal** is every USAJobs posting classified in scope. Each market is described on its own; nothing is pooled across them. Employers are grouped by their normalized name (`companies.normalized_name`).

From `v_employer_postings`.

| Market | Postings | Employers posting | Postings with no company |
|---|---|---|---|
| commercial | 609 | 20 | 7.9% (48 of 609 postings) |
| federal | 5 | 4 | 0.0% (0 of 5 postings) |

## 2. Who posts analyst jobs

### Commercial

- Share of commercial postings from the top 10 employers: 83.7% (510 of 609 postings)

![Bars: the top commercial employers' share of postings](top-employers-commercial.png)

Postings with no company are never an employer; they stay in the denominator. Concentration counts postings, not hires.

| Rank | Employer | Postings (share of the market) |
|---|---|---|
| #1 | Deloitte | 12.8% (78 of 609 postings) |
| #2 | Meta | 11.8% (72 of 609 postings) |
| #3 | Capital One | 9.9% (60 of 609 postings) |
| #4 | CVS Health | 8.9% (54 of 609 postings) |
| #5 | MITRE | 7.9% (48 of 609 postings) |
| #6 | Peraton | 7.9% (48 of 609 postings) |
| #7 | TekSystems | 7.9% (48 of 609 postings) |
| #8 | Acme Analytics | 5.9% (36 of 609 postings) |
| #9 | Geico | 5.9% (36 of 609 postings) |
| #10 | Insight Global | 4.9% (30 of 609 postings) |

### Federal

- Share of federal postings from the top 4 employers: 100.0% (5 of 5 postings)

![Bars: the top federal employers' share of postings](top-employers-federal.png)

Postings with no company are never an employer; they stay in the denominator. Concentration counts postings, not hires.

| Rank | Employer | Postings (share of the market) |
|---|---|---|
| #1 | Department of Veterans Affairs | 40.0% (2 of 5 postings) |
| #2 | Department of Defense | 20.0% (1 of 5 postings) |
| #3 | Department of the Navy | 20.0% (1 of 5 postings) |
| #4 | General Services Administration | 20.0% (1 of 5 postings) |

## 3. Employers with LCA filing history

Postings and employers whose employer matches DOL's LCA disclosure data for FY2024–FY2026 (`v_employer_sponsorship`, `last_3_fy`, on the normalized name). An employer without a match is **no match found**: the name may differ, or the employer may file under another entity. The levels count LCA **filings**, which are not approvals or hires.

From `v_employer_sponsorship_match`; levels are nested. 26 LCA filings loaded in all.

| Employer has | Commercial postings | Commercial employers | Federal postings | Federal employers |
|---|---|---|---|---|
| an LCA filing of any status in the window | 1.1% (7 of 609 postings) | 30.0% (6 of 20 employers) | 0.0% (0 of 5 postings) | 0.0% (0 of 4 employers) |
| ≥ 1 certified H-1B LCA filing | 1.0% (6 of 609 postings) | 25.0% (5 of 20 employers) | 0.0% (0 of 5 postings) | 0.0% (0 of 4 employers) |
| ≥ 1 certified analytics-SOC H-1B LCA filing | 0.8% (5 of 609 postings) | 20.0% (4 of 20 employers) | 0.0% (0 of 5 postings) | 0.0% (0 of 4 employers) |
| no match found | 98.9% (602 of 609 postings) | 70.0% (14 of 20 employers) | 100.0% (5 of 5 postings) | 100.0% (4 of 4 employers) |

## 4. Visa outlook buckets (counts only)

The visa layer's buckets (`v_visa_outlook_summary`, thresholds unchanged), counted per market. **Closed** means the posting itself says no. **Strong** is not a "yes", and **unknown** is never a "no". This section is counts only; the per-job outlook stays in the private Visa outlook dashboard.

Share of each market's in-scope postings.

| Bucket | Commercial | Federal |
|---|---|---|
| closed (the posting says no) | 0.5% (3 of 609 postings) | 60.0% (3 of 5 postings) |
| strong (not a "yes") | 0.7% (4 of 609 postings) | 0.0% (0 of 5 postings) |
| possible | 0.2% (1 of 609 postings) | 0.0% (0 of 5 postings) |
| unknown (no signal; never a "no") | 98.7% (601 of 609 postings) | 40.0% (2 of 5 postings) |

- Commercial closed postings due to a citizenship or clearance requirement: 66.7% (2 of 3 closed postings)
- Federal closed postings due to a citizenship or clearance requirement: 100.0% (3 of 3 closed postings)

Share of each market's closed postings, by the rule that fired.

| Why closed | Commercial | Federal |
|---|---|---|
| posting restriction: citizenship | 33.3% (1 of 3 closed postings) | 100.0% (3 of 3 closed postings) |
| posting restriction: clearance | 33.3% (1 of 3 closed postings) | 0.0% (0 of 3 closed postings) |
| posting: will not sponsor | 33.3% (1 of 3 closed postings) | 0.0% (0 of 3 closed postings) |

Share of each market's unknown postings, by the rule that fired.

| Why unknown | Commercial | Federal |
|---|---|---|
| no signal; employer matched but no certified H-1B LCAs in last 3 FYs | 0.2% (1 of 601 unknown postings) | 0.0% (0 of 2 unknown postings) |
| no signal; no LCA employer match | 99.8% (600 of 601 unknown postings) | 100.0% (2 of 2 unknown postings) |

## 5. Offered wage on matched employers' analytics-SOC LCA filings

The wage employers **offered on their LCA filings** for analytics SOC codes, pooled over the filings of employers that post in each market. It describes filings, never what the postings pay, and the biggest filers dominate it.

From `v_matched_employer_lca_wages`. Median and IQR, never the mean.

| Market | Filings | Offered annual wage on LCA filings | Largest single filer's share | Note |
|---|---|---|---|---|
| commercial | 8 certified analytics-SOC H-1B LCA filings | $90,000 (IQR $79,030–$105,250; n=8 LCA filings from 4 employer(s)) | 50.0% (4 of 8 filings) | directional: under 15 filings or 5 employers |
| federal | 0 certified analytics-SOC H-1B LCA filings | n/a (0 LCA filings with a convertible wage) | n/a (0 of 0 filings) |  |

## What it means

> **[TO WRITE: What it means]** What concentration and the filing record say about where analyst hiring is, and what the measurement can't show (unmatched names, truncated text, filings vs hires).
>
> Numbers from this run to draw on:
> - Commercial postings with no company: 7.9% (48 of 609 postings)
> - Federal postings with no company: 0.0% (0 of 5 postings)
> - Commercial postings at an employer with ≥ 1 certified H-1B LCA filing: 1.0% (6 of 609 postings)
> - Commercial postings in the unknown bucket: 98.7% (601 of 609 postings)
> - Commercial closed postings due to a citizenship or clearance requirement: 66.7% (2 of 3 closed postings)
> - Federal postings at an employer with ≥ 1 certified H-1B LCA filing: 0.0% (0 of 5 postings)
> - Federal postings in the unknown bucket: 40.0% (2 of 5 postings)
> - Federal closed postings due to a citizenship or clearance requirement: 100.0% (3 of 3 closed postings)
> - Commercial: offered wage on matched employers' analytics-SOC LCA filings: $90,000 (IQR $79,030–$105,250; n=8 LCA filings from 4 employer(s))
> - Commercial: share of those filings from the single largest filer: 50.0% (4 of 8 filings)

## What to do about it

> **[TO WRITE: What to do about it]** What a job seeker on F-1 OPT should do with this, at aggregate level. Never a promise about one employer.
>
> Numbers from this run to draw on:
> - Commercial employers with ≥ 1 certified analytics-SOC H-1B LCA filing: 20.0% (4 of 20 employers)
> - Commercial postings in the strong bucket (not a "yes"): 0.7% (4 of 609 postings)
> - Commercial postings in the possible bucket: 0.2% (1 of 609 postings)
> - Federal employers with ≥ 1 certified analytics-SOC H-1B LCA filing: 0.0% (0 of 4 employers)
> - Federal postings in the strong bucket (not a "yes"): 0.0% (0 of 5 postings)
> - Federal postings in the possible bucket: 0.0% (0 of 5 postings)

## Methods and caveats

- Commercial postings: 609
- Federal postings: 5
- Employers are grouped by `companies.normalized_name`; the display name is the first canonical name under it. Postings with no company are counted, never as an employer.
- Concentration: the top 10 employers' share of the market's postings, ties broken by name (the share doesn't depend on the tie-break).
- LCA filings loaded: 26 LCA filings
- Filing window: FY2024–FY2026 (the latest loaded FY and the two before it)
- Match: a posting's normalized employer name equals an LCA employer key in `v_employer_sponsorship` (`last_3_fy`). No fuzzy matching; near-misses go through `src/visa/sponsor_match.py`. Analytics SOC codes, the certified rule and the outlook thresholds are the visa layer's defaults (`sql/views/v_employer_sponsorship.sql`, `v_job_visa_outlook.sql`).
- The offered wage is pooled over filings; under 15 filings or 5 employers it's marked directional.
- The outlook buckets count in-scope postings (`v_job_visa_outlook`); their total can differ from the posting count above while a posting's scope isn't classified yet.
- Privacy: employers are named only beside their posting counts. Every sponsorship number is an aggregate. No job titles, URLs or filing rows appear, and the per-job Visa outlook dashboard stays private.

### What LCA data can't tell you

From src/visa/README.md, "What this can't tell you":

- **An LCA is a filing, not an approval or a hire.** It is the Department of Labor step before an H-1B petition. Employers file more LCAs than they use, and one LCA can cover several positions or none. A count shows willingness to file for a kind of role, not how many people got visas.
- **Counts favour large filers, staffing firms included.** Big employers and IT staffing or outsourcing firms file thousands, so a high count says little about one role, and pooled filing figures (such as a pooled offered wage) are dominated by the biggest filers.
- **"Unknown" is never "no".** An employer with no LCA match is "no match found": the name may differ between the posting and DOL's file, or the employer may file under another entity. Only a posting's own words put it in "closed".
- **Adzuna text is truncated** at about 500 characters, so a sponsorship sentence is often cut off: a missing sentence proves nothing either way.
- **Cap-exempt is only a hint,** from the employer's name. The LCA data has no cap-exempt field; for-profit colleges aren't exempt, and many exempt nonprofits and labs don't say so in their name.
- **E-Verify isn't covered.** The STEM OPT extension needs an E-Verify employer; nothing here checks that.
- **Rules change,** and this describes data; it isn't immigration advice. Check plans with a DSO (and an immigration attorney for anything consequential).
```

</details>

## Parked questions

| Q | Question | Recommendation (built) |
|---|---|---|
| 1 | Should this report ever be published, or kept private like Visa outlook? | (a) the aggregate version is publishable; decide when it's written |
| 2 | What counts as "sponsorship history" in the headline | (a) ≥ 1 certified H-1B LCA in the last 3 FYs, with all three levels shown |
| 3 | Denominator of the match rate | (a) every posting in the market, no-company postings included |
| 4 | Show each top employer's LCA match in the top-employers table? | (a) no: aggregate only |
| 5 | The outlook buckets when LCA data isn't loaded | (a) withheld with the other sponsorship sections |
| 6 | How the offered wage is pooled | (a) over filings, with the largest filer's share beside it |
| 7 | The "directional" threshold for the wage | (a) under 15 filings or 5 employers |
| 8 | The concentration measure | (a) the top 10's share (the brief), nothing more |
| 9 | Flag staffing firms? | (a) no flag; the caveat only |
| 10 | Include the federal market in a sponsorship report | (a) yes, per market as the brief says |
| 11 | Employer display name when several share a key | (a) the alphabetically first canonical name |

### Q1. Publish, or keep private?
- **What I found:** the Visa outlook dashboard is private because it's your job search: per-job verdicts, URLs, and employer-level sponsorship history. This report is aggregate:
  - employers are named only with their posting counts
  - sponsorship appears only as counts and shares across employers
  - the wage is pooled over filings

  Even so, on real data a sentence such as "a quarter of the top employers have filed for analytics roles" sits next to a named top-10 list, and a reader can't tell which ones.
- **Options:**
  - (a) The aggregate version is publishable; decide when the narrative is written.
  - (b) Keep it private, like Visa outlook.
  - (c) Publish only sections 1–2 (hiring), and keep 3–5 private.
- **Recommendation:** (a). Re-read the finished text for anything that singles out an employer before publishing.

### Q2. "Sponsorship history"
- **What I found:** the visa layer's `possible` bucket fires on any certified H-1B LCA in the last 3 FYs. The `strong` bucket needs ≥ 3 analytics-SOC new-employment filings. "Any filing" includes denied and withdrawn ones.
- **Options:**
  - (a) Headline on ≥ 1 certified H-1B filing, and show all three levels in section 3.
  - (b) Headline on analytics-SOC filings only.
  - (c) Headline on any filing.
- **Recommendation:** (a). It's the `possible` threshold, and the table shows the others.

### Q3. Match-rate denominator
- **What I found:** postings with no company can never match.
- **Options:**
  - (a) Every posting in the market, with no-company postings shown separately in section 1.
  - (b) Only postings with a company.
- **Recommendation:** (a). It understates rather than overstates the match rate. The no-company count is beside it.

### Q4. Per-employer match in the top-employers table
- **What I found:** a "has filed" column next to each named employer would rebuild the private dashboard's employer sponsorship table. It would also attach the demo's synthetic LCA data to real employer names.
- **Options:**
  - (a) Aggregate only.
  - (b) Add a matched yes/no column.
  - (c) Add the filing counts.
- **Recommendation:** (a).

### Q5. Buckets without LCA data
- **What I found:** without LCA data, `possible` can't fire and `strong` loses its filing route, so the buckets would show far more `unknown` than the real picture.
- **Options:**
  - (a) Withhold the bucket section with the other two, with the "not loaded" note.
  - (b) Show the text-only buckets with a warning.
- **Recommendation:** (a).

### Q6. Pooling the offered wage
- **What I found:** pooling over filings lets one big filer dominate; in the demo one employer accounts for half the filings. A median of employer medians weights a 2-filing employer like a 2,000-filing one.
- **Options:**
  - (a) Pool over filings, with the largest single filer's share beside it.
  - (b) Median of employer medians.
  - (c) Cap each employer's filings.
- **Recommendation:** (a). It's the honest "what was filed" figure, and the share makes the dominance visible.

### Q7. When the wage is "directional"
- **Options:**
  - (a) Under 15 filings or 5 employers (the commercial drill-down floor, plus an employer floor).
  - (b) No marker.
  - (c) Suppress below the threshold.
- **Recommendation:** (a). `WAGE_MIN_FILINGS` and `WAGE_MIN_EMPLOYERS` in `employers.py`.

### Q8. Concentration measure
- **Options:**
  - (a) The top 10's share, as the brief asks.
  - (b) Add the top 5's share, or a Herfindahl index.
- **Recommendation:** (a). An index is hard to read without a benchmark.

### Q9. Staffing firms
- **What I found:** the caveat says staffing firms inflate filing counts. Flagging them would need a list of real company names, and the repo keeps real names out of fixtures.
- **Options:**
  - (a) No flag; the caveat and the largest-filer share.
  - (b) A local, gitignored list of employer keys you mark as staffing.
- **Recommendation:** (a) now. (b) if the real largest-filer share is high.

### Q10. The federal market
- **What I found:** federal postings mostly require citizenship, and agencies don't file H-1B LCAs, so federal numbers will be near zero.
- **Options:**
  - (a) Keep federal beside commercial, as the brief says.
  - (b) Hiring sections only, for federal.
- **Recommendation:** (a). The near-zero is itself informative, and the closed-by-citizenship share explains it.

### Q11. Display name
- **What I found:** several `companies` rows can share a normalized key after alias folding.
- **Options:**
  - (a) The alphabetically first canonical name.
  - (b) The most frequent one among the postings.
- **Recommendation:** (a). It's deterministic; (b) needs per-posting names in the view.

## What you need to do (on the laptop)

After merging the PR:

```powershell
git checkout main
git pull
uv sync
uv run python scripts/apply_views.py      # four new views (16 in all)
```

**Are your LCA files loaded?** Check:

```powershell
docker compose exec -T db psql -U postgres -d jobmarket -c "select fiscal_year, count(*) from lca_cases group by 1 order by 1"
```

- **No rows:** they aren't loaded. Follow `src/visa/README.md`, steps 1–3: download the latest quarter of each fiscal year from DOL OFLC into `data\lca\`, load them oldest first with `python -m src.visa.lca_loader`, run `apply_views.py`, then `python -m src.cleaning.apply_cleaning --only companies visa`. Until then, report 3 renders its hiring sections and says "LCA data not loaded" in the rest.
- **Rows for the last three fiscal years:** they're loaded. The window is anchored on the latest loaded FY, so load the newest quarter when it's published.

Then:

```powershell
uv run python -m src.reports employers-and-sponsorship
```

- [ ] Open `reports\employers-and-sponsorship\report.md`. Check the stamp (database `jobmarket`, no demo banner) and the filing window in Methods.
- [ ] Optional, for better matches: `python -m src.visa.sponsor_match`, review the CSV, add approved aliases (`src/visa/README.md`, step 4), and re-render.
- [ ] Write the three `[TO WRITE]` sections in a copy (`docs/reports.md`, "Writing the narrative"), then decide Q1 before publishing anything.

## Surprises

- **The wage the brief asks for wasn't in any view.** `v_employer_sponsorship.median_offered_annual_wage` is per employer and over every SOC code, with no IQR or n, and a median of medians would have been wrong. So `v_matched_employer_lca_wages` pools the filings directly, and a test pins its copied rules to the original view.
- **The outlook view is per job.** `v_job_visa_outlook` carries titles and URLs. The report reads a counts-only summary instead, so a job row never reaches it.
- **View order mattered.** The new views can't depend on `v_market_jobs`, which `make views` creates after them in file-name order. They define the same population inline, and a test checks they agree.
- **The demo is lopsided.** 48 of 609 commercial postings have no company, and one employer accounts for half of the matched analytics filings, so the "largest single filer" column is visibly useful. The federal agencies never match an LCA employer.
- **A test of mine was too strict.** A case-insensitive check for "None" matched the word "none" in the LCA caveat ("…several positions or none"). The check is now case-sensitive for `None`.
- **The gate caught a formatting slip** after a scripted edit. I reformatted and re-ran the whole gate before committing.

**How I know no live API was called:**

- No ingestion ran, and no LCA file was downloaded or loaded: every database was filled by `seed_demo_data.py --full`, which uses fixture-backed clients and the seed's own FAKE LCA rows.
- Network use was GitHub only: `git push`, and the GitHub MCP for CI status.

## Suggested PR title

**Report 3: who hires data analysts and who has filed to sponsor them (aggregate, LCA guardrails, demo data)**

<details>
<summary>PR description (ready to paste)</summary>

## Summary

Milestone F: Phase 5's third report. It covers which employers post analyst jobs, how concentrated hiring is, and how many of those employers have a record of H-1B LCA filings for analytics roles. Built with the report kit, on demo data, with no findings written: the narrative sections are placeholders with this run's numbers.

- **LCA guardrails** (`src/reports/lca_guardrails.py`), from `src/visa/README.md`'s "What this can't tell you":
  - filing counts must say "LCA filings" and can't be called hires or approvals
  - the offered wage is "on LCA filings", never what postings pay
  - unmatched is "no match found", and "unknown" is never "no"; rendered text claiming an employer doesn't sponsor is refused
  - Methods must print the caveats
  - frames with job ids, titles, URLs or case numbers are refused
- **Four aggregate views:**
  - `v_employer_postings`
  - `v_employer_sponsorship_match` (three nested match levels, plus whether LCA data is loaded)
  - `v_visa_outlook_summary` (counts only, so the report never loads the per-job view behind the private dashboard)
  - `v_matched_employer_lca_wages` (filing-level wage distribution; repeats `v_employer_sponsorship`'s rules, pinned by a test)
- **Report 3** (`make report REPORT=employers-and-sponsorship`), per market, never pooled:
  - top employers and the top 10's share of postings
  - LCA match levels
  - outlook bucket counts and why closed / unknown
  - the offered wage on analytics-SOC filings (median + IQR, n, largest filer's share)
  - Methods and caveats
  - `[TO WRITE]` placeholders
  - without LCA data, the sponsorship sections say "LCA data not loaded"
- **Privacy:** employers are named only beside posting counts, and every sponsorship number is aggregate.

## Testing

- `pytest` with `TEST_DATABASE_URL`: 518 → **553 passed**, 1 skipped.
- `ruff check .` / `ruff format --check .` (0.17.2) clean; alembic round trip clean; `make views` applies 16 views, twice.
- A golden file with FAKE names and invented numbers.
- Unit tests for every LCA guardrail.
- The views tested on hand-built rows (withdrawn, E-3, out-of-window and hourly filings) and with no LCA data.
- Demo cross-checks against `v_market_jobs`, `v_job_visa_outlook` and `v_employer_sponsorship`.
- End-to-end CLI runs on the demo seed, with LCA data and after emptying `lca_cases`.
- No job or government API was called, no LCA file was loaded, and no rendered output is committed.

## Open questions

11 parked decisions are in `docs/overnight-employer-report.md`, each with the default that was built:
- whether to publish (aggregate version publishable; decide when written)
- the "sponsorship history" level
- the match denominator
- per-employer match columns
- buckets without LCA data
- wage pooling
- the directional threshold
- the concentration measure
- staffing firms
- the federal market
- display names

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01ATh4ABgiML8G58MzgJ36ZP

</details>
