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
.xlsx per fiscal-year quarter (tens to 100+ MB each). Files are
**cumulative within a fiscal year** (a Q3 file includes Q1 and Q2), so you
need just the **latest quarter of each fiscal year**. The federal FY runs
October to September: FY2026 = Oct 2025 to Sep 2026.

```bash
mkdir -p data/lca        # data/ is gitignored, so these files are never committed
# save e.g. data/lca/LCA_Disclosure_Data_FY2024_Q4.xlsx
#           data/lca/LCA_Disclosure_Data_FY2025_Q4.xlsx
#           data/lca/LCA_Disclosure_Data_FY2026_Q4.xlsx   (or the latest quarter out)
```

## 2. Load them

```bash
alembic upgrade head                                     # creates lca_cases, job_visa_signals
python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2026_Q4.xlsx \
    --fiscal-year 2026 --dry-run                         # parse + count, write nothing
python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2024_Q4.xlsx --fiscal-year 2024
python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2025_Q4.xlsx --fiscal-year 2025
python -m src.visa.lca_loader --file data/lca/LCA_Disclosure_Data_FY2026_Q4.xlsx --fiscal-year 2026
```

Each run prints rows read, cases upserted, skipped rows, bad cells nulled
per column, and counts by `case_status` and `visa_class`. Reloading a
later, cumulative quarter of the same FY upserts on `case_number`, so
nothing is counted twice. **Load in chronological order**, since the latest load wins.
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

## 4. Review employer matches

Postings join to LCA history on `companies.normalized_name = lca_cases.employer_key`.
Near-misses ("fakeco" vs "fakeco analytics") are proposed for review:

```bash
python -m src.visa.sponsor_match                         # -> data/sponsor_match_candidates.csv
```

Open the CSV and mark `approved` (e.g. `y`) on pairs that are really the
same employer. Nothing is merged automatically. For each approved pair, add
an alias to `src/cleaning/data/company_aliases.json` that maps one key to
the other, e.g. `"fakeco analytics": "fakeco"`. Then re-key both sides:

```bash
python -m src.cleaning.apply_cleaning --only companies
python -m src.visa.lca_loader --rekey
```

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
