# Visa-sponsorship layer

For every in-scope job: how open it looks to someone on **F-1 OPT who will
later need H-1B sponsorship**, and the evidence behind that. Three
independent signals end up in one view (`v_job_visa_outlook`) and one CLI
(`python -m src.visa.scan`):

1. **Employer history**: DOL's public LCA disclosure files → `lca_cases` → `v_employer_sponsorship`
2. **Posting text**: citizenship or clearance required, will or won't sponsor, OPT/CPT mentioned → `job_visa_signals`
3. **Cap-exempt hint**: universities and colleges, from the company name only

Same rules as the cleaning layer (`src/cleaning/README.md`): flag, don't
guess; precision over recall, with a trap test before every rule; layer,
don't destroy; everything recomputable. Every column and judgment call is
in [`docs/data_dictionary.md`](../../docs/data_dictionary.md) ("Visa-sponsorship layer").

## 1. Download the LCA files (by hand, into `data/lca/`)

DOL's Office of Foreign Labor Certification (OFLC) publishes **LCA Programs
(H-1B, H-1B1, E-3) disclosure data** on its *Performance Data* page, one
.xlsx per fiscal-year quarter (tens to 100+ MB each). The federal FY runs
October to September: FY2026 = Oct 2025 to Sep 2026.

**Some fiscal years' quarterly files hold one quarter each and others are
cumulative; load every quarterly file for each fiscal year, oldest first.
Overlaps are upserted on `case_number`.** By `DECISION_DATE`, the FY2024 Q4
and FY2025 Q4 files each hold July to September only, while the FY2026 Q3
file holds October 2025 to June 2026. A file's name doesn't tell you which
kind it is; the loader's coverage output does (step 2).

For the 3-fiscal-year window the views use, download:

- **every quarter (Q1 to Q4) of the two earlier fiscal years**, and
- **the latest file of the current fiscal year**. The FY2026 Q3 file is the
  year to date. If the current year's coverage output shows a single quarter,
  download that year's earlier quarters too.

```bash
mkdir -p data/lca        # data/ is gitignored, so these files are never committed
# e.g. for FY2024-FY2026, save:
#   data/lca/LCA_Disclosure_Data_FY2024_Q1.xlsx ... LCA_Disclosure_Data_FY2024_Q4.xlsx
#   data/lca/LCA_Disclosure_Data_FY2025_Q1.xlsx ... LCA_Disclosure_Data_FY2025_Q4.xlsx
#   data/lca/LCA_Disclosure_Data_FY2026_Q3.xlsx   (the latest out)
```

## 2. Load them

```bash
alembic upgrade head                                     # creates lca_cases, job_visa_signals
python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2024_Q1.xlsx \
    --fiscal-year 2024 --dry-run                         # parse + count, write nothing
# then every file, oldest first, each with its own --fiscal-year
for q in 1 2 3 4; do
  python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2024_Q$q.xlsx --fiscal-year 2024
done
for q in 1 2 3 4; do
  python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2025_Q$q.xlsx --fiscal-year 2025
done
python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2026_Q3.xlsx --fiscal-year 2026
```

Each run, dry run included, prints rows read, cases upserted, skipped rows,
bad cells nulled per column, flags marked `N/A`, and counts by `case_status`
and `visa_class`. Then it prints the file's **coverage**:

- the fiscal year's dates and the earliest and latest `DECISION_DATE`;
- cases per calendar month of `DECISION_DATE`, with a month that has none
  shown as 0. A one-quarter file shows three months; a year-to-date file
  shows every month since October;
- how many cases were decided outside the `--fiscal-year` given. Any such
  case gets a warning. If more than 1% of the file's cases are outside it,
  the load is **refused and nothing is written** (in a dry run too), unless
  you pass `--allow-outside-fy`. That catches a mislabelled fiscal year
  before it shifts the 3-FY window.

A case that appears in two files (a cumulative file overlapping an earlier
one) is upserted on `case_number`, so nothing is counted twice. **Load in
chronological order**, since the latest load wins.

The files name the H-1B dependency column `H_1B_DEPENDENT`; the loader also
accepts `H-1B_DEPENDENT`, matched exactly, and refuses a file carrying both.
`N/A` in `H_1B_DEPENDENT`, `WILLFUL_VIOLATOR` or `FULL_TIME_POSITION` means
"not applicable": it loads as NULL and is counted apart from bad cells.

Only an explicit column allowlist is read. The contact, attorney and
preparer columns (real people's names, emails and phone numbers) never
reach the database.

## 3. Apply the views and classify postings

```bash
make views                                               # all sql/views/*.sql, in order, one transaction
python -m src.cleaning.apply_cleaning --only companies visa
```

`apply_cleaning` with no `--only` now runs the `visa` step last. The step
rebuilds `job_visa_signals` from stored text every time, so it's safe to re-run.

Check what each loaded fiscal year holds:

```sql
select * from v_lca_coverage order by fiscal_year;
```

One row per fiscal year: `n_cases`, `min_decision_date`, `max_decision_date`
and `n_months_with_decisions`. A complete fiscal year shows 12 months; the
current one fewer (9 when loaded to June). Fewer months than expected, or a
late `min_decision_date`, means a quarterly file is missing.

## 4. Review employer matches

Postings join to LCA history on `companies.normalized_name = lca_cases.employer_key`.
Near-misses ("fakeco" vs "fakeco analytics") are proposed for review:

```bash
python -m src.visa.sponsor_match                         # -> data/sponsor_match_candidates.csv
```

Open the CSV and mark `approved` (`y`, `yes`, `x`, `1` or `true`) on pairs
that are really the same employer. Nothing is merged automatically. Then let
the helper promote them into `src/cleaning/data/company_aliases.json`:

```bash
python -m src.cleaning.aliases apply --from data/sponsor_match_candidates.csv          # dry run
python -m src.cleaning.aliases apply --from data/sponsor_match_candidates.csv --write
```

The dry run shows what it would add, the rows it refuses and why, and the
JSON diff. By default the longer key is mapped onto the shorter one (e.g.
`"fakeco analytics": "fakeco"`); add a `keep_company` or `keep_lca` column
and mark it to choose the key that survives. After `--write` it prints the
commands that re-key both sides:

```bash
python -m src.cleaning.apply_cleaning --only companies
python -m src.visa.lca_loader --rekey
python scripts/apply_views.py
```

Then re-render Report 3. Fallback, by hand: add the alias to the JSON
yourself (see `src/cleaning/README.md`) and run the same commands.

Be strict: a staffing firm and a client with similar names are **not** the
same employer, and LCA counts belong to the filer.

## 5. Scan

```bash
python -m src.visa.scan --bucket strong --metro NYC --limit 50
python -m src.visa.scan --csv data/visa_scan.csv         # keep outputs under data/ (gitignored)
```

For each job the scan prints the title, company, metro and bucket, the reason
for the bucket, the posting signals with the matched phrases, the employer's
last-3-FY certified H-1B counts (all / new employment / analytics SOC / both),
its wage-level mix and median offered wage, and the `redirect_url`. It shows
employer-level aggregates only, never an individual LCA row.

Buckets (first match wins): **closed** (citizenship or clearance required, or
won't sponsor) → **strong** (will sponsor, or ≥ 3 certified analytics-SOC
new-employment H-1B LCAs in the last 3 FYs, or likely cap-exempt) →
**possible** (any certified H-1B LCA in the last 3 FYs) → **unknown**.

## What this can't tell you

- **An LCA is not an approval or a hire.** An LCA is the Department of Labor
  step before an H-1B petition. Employers file more LCAs than they use, and
  one LCA can cover several positions or none that are ever filled. A count
  of LCAs shows an employer's *willingness to file* for a kind of role. It
  doesn't show how many people got visas.
- **Counts favour large filers, staffing firms included.** Big employers and
  IT staffing or outsourcing firms file thousands. A high count doesn't mean
  they'll sponsor *you* for *this* role, and a small employer with two
  filings may be a better fit. Look at the analytics-SOC and new-employment
  subsets, and the H-1B-dependent flag, before the headline number.
- **A partial current fiscal year makes the 3-FY window uneven.** The window
  is the latest fiscal year loaded and the two before it. While the latest
  is partial (FY2026 loaded to June is nine months), it holds fewer filings
  than the two complete years. So a recent sponsor looks smaller than it is,
  and FY-to-FY comparisons aren't like for like. `v_lca_coverage` shows how
  many months each year holds.
- **Truncated text hides signals.** Adzuna descriptions are capped at about 500
  characters, so "we are unable to sponsor" is often in the part that was cut
  off. `none_found` on `truncated` text means *unknown*, never "sponsors".
  Read the full posting at `redirect_url` before applying.
- **Cap-exempt is only a hint.** It comes from the company name alone. The
  LCA data has no cap-exempt field. For-profit colleges aren't exempt, and
  many affiliated nonprofits, research organisations and government labs
  are exempt but don't say so in their name. Confirm with the employer's HR
  or international office.
- **E-Verify isn't covered.** The STEM OPT extension requires an employer
  enrolled in E-Verify. Nothing here checks that, so verify it separately for
  any STEM OPT plan.
- **Rules change.** Lottery weighting, fees and OPT rules have all changed
  recently and will change again. This tool describes data. It doesn't give
  immigration advice. Check your plans with your school's DSO (and an
  immigration attorney for anything consequential).
