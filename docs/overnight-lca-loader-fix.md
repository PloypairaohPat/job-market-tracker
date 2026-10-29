# Overnight run: the LCA loader, fixed for DOL's real file layout

## Report

- **Branch:** `claude/lca-loader-fix`, off `main` at `7656b01` ("Merge pull request #6 from PloypairaohPat/claude/employer-report"). This session's setup named a different working branch; per the brief, everything went to `claude/lca-loader-fix`.
- **Commits on top of main `7656b01`:** 4, plus this report (listed below). **Pushed:** yes, after every green commit. No force push, nothing to `main`, no PR.
- **STOP conditions:** none held.
  - `7656b01` is in main's history (it was main's head).
  - The baseline on clean main was green: **553 passed, 1 skipped**.
  - `alembic heads` showed one head, `a02471448340`.
  - Main had no fix for `H_1B_DEPENDENT`. Its `COLUMN_MAP` knew only `H-1B_DEPENDENT`, and no remote branch or commit touched it.
- **Verification setup:**
  - Local Postgres 16 on 127.0.0.1, with a freshly recreated `jobmarket_test` before every commit.
  - A gate script that **exits on the first failure**: pytest with `TEST_DATABASE_URL`, `ruff check .`, `ruff format --check .` (0.17.2), the alembic upgrade → downgrade → upgrade round trip on a recreated database, and `make views` twice. It stopped one commit at `ruff format`; I fixed the formatting and re-ran the whole gate.
  - Versions: Python 3.13.17, SQLAlchemy 2.1.6, alembic 1.20.1, pandas 3.1.0, openpyxl 3.1.5, pytest 9.1.1, ruff 0.17.2.
- **Data:** synthetic only. Every test file is an .xlsx or .csv built in a temp dir from invented values, with FAKE employer names and invented personal-data columns. No LCA file was downloaded or loaded. No dol.gov, job or government site was called.
- **Compare:** https://github.com/PloypairaohPat/job-market-tracker/compare/main...claude/lca-loader-fix?expand=1

| Check | Baseline (clean main) | Final |
|---|---|---|
| `pytest` with `TEST_DATABASE_URL` | 553 passed, 0 failed, 1 skipped | **577 passed, 0 failed, 1 skipped** (+24: header aliases 8, N/A flags 8, coverage and the fiscal-year guard 8). The skip is the Metabase e2e test, which needs `METABASE_URL` |
| `ruff check .` (0.17.2) | clean | clean |
| `ruff format --check .` (0.17.2) | clean, 133 files | clean, 134 files (ruff 0.17 counts Markdown too, this report included) |
| alembic upgrade → downgrade → upgrade on a recreated database | clean | clean (no migration: `lca_cases` is unchanged) |
| `make views` on a fresh database, twice | 16 views | **17 views**, twice (`v_lca_coverage` added) |
| `git grep -n -i cumulative -- src docs/data_dictionary.md` | 4 claims that files are cumulative within a FY | 5 lines, all the corrected wording ("some … hold one quarter each and others are cumulative") |
| GitHub Actions CI on the branch | — | **#49, #50, #51 green** (one per code commit); #52 (docs) was still running when this was written |

### Acceptance criteria

| # | Criterion | Where it's tested |
|---|---|---|
| 1 | `H_1B_DEPENDENT` file with Yes / No / N/A / blank in both flags: flags populated, N/A counted as `not_applicable`, 0 bad cells, .xlsx and .csv | `test_na_flags_load_as_null_and_are_not_bad_cells[.csv/.xlsx]`, `test_na_only_input_has_no_bad_cells`, `test_either_spelling_loads_the_h1b_flag` |
| 2 | Every existing test passes; personal-data columns still excluded | all 553 baseline tests pass; `test_file_loads_and_personal_data_never_reaches_db`, `test_column_map_has_no_personal_data_columns`, `test_aliases_are_exact_and_carry_no_personal_data`, and the alias tests check the personal-data values too |
| 3 | Coverage output and `v_lca_coverage` correct on a two-quarter, two-file fixture; the guard refuses above 1% and passes with the flag | `test_coverage_of_two_quarterly_files_and_v_lca_coverage`, `test_up_to_one_percent_outside_the_fiscal_year_warns_but_loads`, `test_more_than_one_percent_outside_is_refused_in_a_dry_run_too`, `test_a_mislabelled_fiscal_year_writes_nothing_unless_allowed`, `test_cli_prints_coverage_and_exits_non_zero_when_refused` |
| 4 | No doc claims every file is cumulative | the grep row above |
| 5 | Suite green, ruff clean, round trip clean, `make views` twice | the table above |
| 6 | Nothing real committed; no network except GitHub | see "How I know" below |

## What shipped

| # | Commit | What |
|---|---|---|
| 1 | `17b4517` | Header aliases, so `H_1B_DEPENDENT` loads |
| 2 | `1f2557b` | `N/A` in a flag column means not applicable, not a bad cell |
| 3 | `694e453` | Coverage in the loader output, the outside-FY guard, `v_lca_coverage` |
| 4 | `14d7ad8` | Docs: quarterly files aren't all cumulative; `Certified - Withdrawn` |
| 5 | (this) | This report |

**1. Header aliases.**
- `COLUMN_MAP` stays the one allowlist (source header → `lca_cases` column), and `h1b_dependent` now has two entries: `H-1B_DEPENDENT` and `H_1B_DEPENDENT`. Matching is exact; there's no fuzzy or case-insensitive matching. `ALIASES` (column → every header accepted) is derived from it, so the personal-data test still covers every alias.
- The readers translate headers to `lca_cases` columns as they read. A missing alias can't overwrite a present one.
- A file carrying two *different* spellings of one column is refused (`AmbiguousColumnsError`): "… has both 'H-1B_DEPENDENT' and 'H_1B_DEPENDENT', two spellings of h1b_dependent: keep one of them and reload".
- Missing-column warnings and errors name the column and every header tried: `h1b_dependent (H-1B_DEPENDENT, H_1B_DEPENDENT)`.

**2. `N/A` in flag columns.**
- `parse_flag` reads `N/A`, `NA`, `n/a` (trimmed, any case) as NULL, and they don't count as bad cells.
- `LoadResult.not_applicable` counts them per column, and the summary prints `flags marked N/A (not applicable), loaded as NULL: {…}`.
- Any other unrecognized value (`N.A.`, `Unknown`, `maybe`) is still a bad cell.
- This applies to all three flag columns: `h1b_dependent`, `willful_violator`, `full_time_position`.

**3. Coverage, the fiscal-year guard, `v_lca_coverage`.**
- Every load, dry run included, ends with the file's coverage, computed over the distinct cases kept:
  - the fiscal year's dates
  - the earliest and latest `DECISION_DATE`
  - cases per calendar month, with a month that has none printed as 0, so a gap is visible
  - cases with no decision date
  - cases decided outside the `--fiscal-year` given
- **The guard.** Any case decided outside 1 Oct of FY−1 to 30 Sep of FY gets a warning with the count. If more than 1% of the file's cases are outside (`OUTSIDE_FY_MAX_SHARE`), the load raises `OutsideFiscalYearError` before writing anything. It does this in a dry run too. The CLI then prints the full summary, including the coverage, and exits non-zero. `--allow-outside-fy` (or `load_file(..., allow_outside_fy=True)`) loads anyway, keeping the warning.
- **`v_lca_coverage`** has one row per `fiscal_year`: `n_cases`, `min_decision_date`, `max_decision_date`, `n_months_with_decisions`. It's aggregate only and documented in its header comment and in `docs/data_dictionary.md`.

Sample dry run, on a synthetic file (FAKE employer, invented case numbers) that uses `H_1B_DEPENDENT`, has N/A flags, and has no January decisions:

```text
rows read: 7
cases parsed (dry run, nothing written): 7
skipped (no CASE_NUMBER): 0
duplicate CASE_NUMBERs within file (last kept): 0
bad cells nulled: none
flags marked N/A (not applicable), loaded as NULL: {'h1b_dependent': 2, 'willful_violator': 2}
by case_status:
  Certified              7
by visa_class:
  H-1B                   7
FY2026 runs 2025-10-01 to 2026-09-30
DECISION_DATE coverage: 2025-10-02 to 2026-02-03
cases per month of DECISION_DATE:
  2025-10  1
  2025-11  3
  2025-12  2
  2026-01  0
  2026-02  1
no DECISION_DATE: 0
decided outside FY2026: 0
```

And the same file run with the wrong `--fiscal-year 2025` (exit code 1):

```text
decided outside FY2025: 6  <-- WARNING: check --fiscal-year
refused: LCA_FAKE_FY2026_Q2.xlsx: 6 of 7 cases (85.7%) were decided outside FY2025 (2024-10-01 to 2025-09-30), more than 1%: check --fiscal-year, or pass --allow-outside-fy to load anyway. Nothing was written.
```

**4. Docs and wording.**
- Every claim that files are cumulative within a fiscal year was corrected: the loader docstring, the model docstring, `src/visa/README.md` and `docs/data_dictionary.md`. They now carry the new rule: "Some fiscal years' quarterly files hold one quarter each and others are cumulative; load every quarterly file for each fiscal year, oldest first. Overlaps are upserted on `case_number`."
- **`src/visa/README.md`:**
  - Step 1 lists what to download for a 3-FY window: every quarter of the two earlier fiscal years, plus the latest file of the current one (and that year's earlier quarters, if its coverage shows a single quarter).
  - Step 2 loads every file oldest first, and explains the coverage output, the guard and the two header spellings.
  - Step 3 shows how to read `v_lca_coverage`.
  - "What this can't tell you" now notes that a partial current fiscal year (FY2026 to June) makes the 3-FY window uneven.
- `Certified - Withdrawn`, spelled with spaces as in the files, replaces `Certified-Withdrawn` in the model comment, the `v_employer_sponsorship.sql` header comment and `docs/data_dictionary.md`, and in two tests' data. No SQL logic changed: the views still test `case_status = 'Certified'` exactly.
- The data dictionary's allowlist paragraph now says 30 columns from 31 exact header names. The flags row documents the alias and N/A.
- The test `test_cumulative_quarter_reload_does_not_double_count` is renamed `test_reloading_an_overlapping_file_does_not_double_count` and tests the same thing.

## Parked questions

Each has the default that was built.

| # | Question | Built (default) |
|---|---|---|
| 1 | A file carries two different spellings of one column | (a) refuse |
| 2 | Fuzzy or case-insensitive header matching | (a) none: exact aliases only |
| 3 | What `N/A` in a flag column becomes | (a) NULL, counted as `not_applicable` |
| 4 | The outside-FY refusal threshold and its denominator | (a) more than 1% of the file's distinct cases |
| 5 | Does the guard refuse in a dry run too? | (a) yes, non-zero exit |
| 6 | Warn on a sparse month (October 2025)? | (a) no: the per-month counts show it |
| 7 | The demo seed's `Certified-Withdrawn` spelling | (a) left as is |
| 8 | Should Report 3's Methods cite `v_lca_coverage`? | (a) not yet |
| 9 | The uneven 3-FY window while the current FY is partial | (a) documented caveat only |
| 10 | Older overnight reports still give the old download advice | (a) left as dated records |

### Q1. Two spellings of one column in one file
- **What I found:** no real file has both, but a future DOL release could rename a column halfway through its life.
- **Options:**
  - (a) Refuse the file, naming both headers.
  - (b) Prefer one spelling, e.g. the newer `H_1B_DEPENDENT`.
  - (c) Per row, take whichever is non-blank.
- **Recommendation:** (a). Two spellings in one file means the layout changed in a way nobody has looked at. Refusing costs one manual fix; guessing could silently load the wrong column.

### Q2. Fuzzy or case-insensitive header matching
- **Options:**
  - (a) Exact aliases only, each added by hand when DOL renames a column.
  - (b) Case-insensitive matching.
  - (c) Normalize punctuation (`-`, `_`, spaces) before matching.
- **Recommendation:** (a). The allowlist is the personal-data firewall. Exact names keep it reviewable: every header that can reach the database is written out in `COLUMN_MAP`. A rename shows up as a missing-column warning naming every header tried.

### Q3. What `N/A` becomes
- **What I found:** `N/A` is about 2.4% of FY2026's `WILLFUL_VIOLATOR` and `H_1B_DEPENDENT` cells. It plausibly marks the E-3 / H-1B1 treaty filings, but that's unconfirmed.
- **Options:**
  - (a) NULL, counted per column as not applicable.
  - (b) A third value. That needs a text column and a migration, which is out of scope.
  - (c) False.
- **Recommendation:** (a). The views' `any_h1b_dependent` / `any_willful_violator` already ignore NULLs, and (c) would assert something the file doesn't. To check the treaty-visa theory after loading:
  ```sql
  select visa_class, count(*) from lca_cases where willful_violator is null group by 1 order by 2 desc;
  ```

### Q4. The outside-FY threshold
- **What I found:** every file the owner measured lies inside its own fiscal year, so none of them trips the guard. The FY2024 and FY2025 Q1–Q3 files haven't been measured yet.
- **Options:**
  - (a) Refuse above 1% of the file's distinct cases. Cases with no decision date count in the denominator; the real files have none.
  - (b) Refuse on any case outside the fiscal year.
  - (c) A looser 5%.
  - (d) Warn only.
- **Recommendation:** (a). A mislabelled fiscal year puts close to 100% of cases outside, so 1% catches it with room to spare. A handful of stray dates only warns, and `--allow-outside-fy` covers a file that is legitimately odd.

### Q5. The guard in a dry run
- **Options:**
  - (a) A dry run refuses the same way, exiting non-zero after printing the coverage.
  - (b) A dry run only warns.
- **Recommendation:** (a). A dry run should predict the real load, so the owner sees the refusal before loading anything.

### Q6. Sparse months
- **What I found:** October 2025 has 1,459 decisions, against 34K–80K in every other month. One plausible cause is the federal shutdown that began on 1 October 2025, but that's unconfirmed, and nothing in the code depends on it.
- **Options:**
  - (a) No extra warning: the per-month counts already make it visible.
  - (b) Warn when a month falls below, say, 10% of the file's median month.
- **Recommendation:** (a) for now. If a sparse month ever hides a missing file, add (b). Either way, read FY2026's October as a processing gap, not low demand.

### Q7. The demo seed's spelling
- **What I found:** `src/dashboard/demo_dataset.py` seeds one LCA row as `Certified-Withdrawn`. It's data, not a comment, and the dashboards are out of scope. No logic depends on it, since only `= 'Certified'` counts.
- **Options:**
  - (a) Leave it.
  - (b) Align it to `Certified - Withdrawn` in a later small PR.
- **Recommendation:** (b), whenever the demo seed is next touched.

### Q8. Report 3 and `v_lca_coverage`
- **Options:**
  - (a) Leave Report 3 alone (built; Report 3 is out of scope).
  - (b) Its Methods section prints the months each fiscal year in the window holds, from `v_lca_coverage`.
  - (c) Also flag a partial latest fiscal year in the text.
- **Recommendation:** (b), in a follow-up. The uneven window (Q9) changes how Report 3's filing counts read, and a reader should see it next to the numbers.

### Q9. The uneven 3-FY window
- **What I found:** with FY2026 loaded to June, the window is 12 + 12 + 9 months. Recent filers look smaller than they are, and fiscal-year comparisons aren't like for like.
- **Options:**
  - (a) A documented caveat (built: README, "What this can't tell you").
  - (b) Anchor the window on the latest *complete* fiscal year.
  - (c) Show the partial year separately.
- **Recommendation:** (a) plus Q8 (b). Changing the window changes the visa thresholds' meaning, which is out of scope here. Revisit when FY2026 Q4 is out.

### Q10. Older overnight reports
- **What I found:**
  - `docs/overnight-visa-layer.md` still describes a "Cumulative reload" check (Q3 then Q4 should equal the Q4 file's row count), which is wrong for one-quarter files.
  - `docs/overnight-employer-report.md` still says to download the latest quarter of each fiscal year.
  - Both spell the status `Certified-Withdrawn`.
- **Options:**
  - (a) Leave them as dated records. `src/visa/README.md` is the live instruction.
  - (b) Add a one-line "superseded by src/visa/README.md" note to each.
- **Recommendation:** (b), in the PR that merges this, if you want them read again; otherwise (a).

## What you run on the laptop after merging (Windows PowerShell, uv)

```powershell
git checkout main
git pull
uv sync
uv run python scripts/apply_views.py      # adds v_lca_coverage (17 views in all)
```

**Download** FY2024 Q1, Q2, Q3 and FY2025 Q1, Q2, Q3 from DOL OFLC's Performance Data page into `data\lca\`, next to the three files already there:

```text
data\lca\LCA_Disclosure_Data_FY2024_Q1.xlsx   (new)
data\lca\LCA_Disclosure_Data_FY2024_Q2.xlsx   (new)
data\lca\LCA_Disclosure_Data_FY2024_Q3.xlsx   (new)
data\lca\LCA_Disclosure_Data_FY2024_Q4.xlsx
data\lca\LCA_Disclosure_Data_FY2025_Q1.xlsx   (new)
data\lca\LCA_Disclosure_Data_FY2025_Q2.xlsx   (new)
data\lca\LCA_Disclosure_Data_FY2025_Q3.xlsx   (new)
data\lca\LCA_Disclosure_Data_FY2025_Q4.xlsx
data\lca\LCA_Disclosure_Data_FY2026_Q3.xlsx
```

**Dry-run each file**, then **load them in this order**: FY2024 Q1, Q2, Q3, Q4, then FY2025 Q1, Q2, Q3, Q4, then FY2026 Q3, each with its own `--fiscal-year`:

```powershell
$files = @(
  @{ f = "LCA_Disclosure_Data_FY2024_Q1.xlsx"; fy = 2024 },
  @{ f = "LCA_Disclosure_Data_FY2024_Q2.xlsx"; fy = 2024 },
  @{ f = "LCA_Disclosure_Data_FY2024_Q3.xlsx"; fy = 2024 },
  @{ f = "LCA_Disclosure_Data_FY2024_Q4.xlsx"; fy = 2024 },
  @{ f = "LCA_Disclosure_Data_FY2025_Q1.xlsx"; fy = 2025 },
  @{ f = "LCA_Disclosure_Data_FY2025_Q2.xlsx"; fy = 2025 },
  @{ f = "LCA_Disclosure_Data_FY2025_Q3.xlsx"; fy = 2025 },
  @{ f = "LCA_Disclosure_Data_FY2025_Q4.xlsx"; fy = 2025 },
  @{ f = "LCA_Disclosure_Data_FY2026_Q3.xlsx"; fy = 2026 }
)

# 1. dry runs: nothing is written; stop at the first refusal
foreach ($x in $files) {
  uv run python -m src.visa.lca_loader --file "data\lca\$($x.f)" --fiscal-year $x.fy --dry-run
  if ($LASTEXITCODE -ne 0) { Write-Host "STOP: $($x.f)"; break }
}
```

In each dry run's output, check that:
- `bad cells nulled` is `none` or tiny, and `flags marked N/A` carries the N/A counts instead;
- no "allowlisted columns absent" line appears (the H-1B flag now loads);
- `DECISION_DATE coverage` and the per-month counts match the file. FY2024 and FY2025 quarters each show three months, FY2026 Q3 shows October 2025 to June 2026 (October will be small; see Q6);
- `decided outside FY…` is 0.

```powershell
# 2. the real loads, oldest first; stop at the first failure
foreach ($x in $files) {
  uv run python -m src.visa.lca_loader --file "data\lca\$($x.f)" --fiscal-year $x.fy
  if ($LASTEXITCODE -ne 0) { Write-Host "STOP: $($x.f)"; break }
}
```

If you already loaded any of the three files with the old loader, reloading it overwrites every column, `h1b_dependent` included. Nothing needs cleaning up first.

**Check `v_lca_coverage`.** FY2024 and FY2025 should each show 12 months, and FY2026 nine:

```powershell
docker compose exec -T db psql -U postgres -d jobmarket -c "select * from v_lca_coverage order by fiscal_year"
```

A year with fewer months, or a late `min_decision_date`, means a quarterly file is missing: download it and load it, keeping the order.

**Then:**

```powershell
uv run python -m src.cleaning.apply_cleaning --only companies visa
uv run python -m src.reports employers-and-sponsorship
```

- [ ] Open `reports\employers-and-sponsorship\report.md`. The filing window in Methods should read FY2024–FY2026, and `lca_rows_loaded` should now include every quarter.
- [ ] Decide Q8 and Q9 before publishing anything that compares fiscal years.

## Surprises

- **The coverage output can't tell a one-quarter file from a cumulative one by itself, but it makes the difference obvious.** Three months versus nine is plain in the per-month counts. So the README tells you to read the output rather than trusting the file name.
- **The guard only refuses, it never fixes.** A refused load writes nothing. `--allow-outside-fy` is the deliberate override, and the warning is still printed.
- **A dry run that refuses exits non-zero.** That's why the PowerShell loops above check `$LASTEXITCODE`.
- **An earlier test already used the files' spelling.** `tests/test_employer_report_views.py` had `Certified - Withdrawn`. The demo seed still has the old spelling (Q7).
- **October 2025 is a near-empty month** in FY2026 (see Q6). It will make FY2026 look a little smaller than nine full months.
- **The gate caught a formatting slip.** A model comment pushed one line over ruff's limit. I shortened the comment and re-ran the whole gate before committing.

**How I know nothing real went in and no live site was called:**

- Every LCA row in the tests is built inside the test from invented values: FAKE employer names, invented case numbers, invented personal-data values. The two sample outputs above come from the same kind of synthetic file, written to a scratch directory outside the repo and not committed.
- The only real-file facts in this branch are the aggregate measurements the brief gave: the header names, the date ranges and the `case_status` spellings. There are no rows, case numbers or employer names.
- Network use was GitHub only: `git push`, and the GitHub MCP for CI status.

## Suggested PR title

**LCA loader: load DOL's real files (H_1B_DEPENDENT alias, N/A flags, coverage output, fiscal-year guard, v_lca_coverage)**

<details>
<summary>PR description (ready to paste)</summary>

## Summary

Dry runs on the real DOL LCA disclosure files (FY2024 Q4, FY2025 Q4, FY2026 Q3) exposed two loader bugs and a wrong assumption in the docs. This fixes all three. There's no schema change and no migration.

- **Header aliases.** The files spell the column `H_1B_DEPENDENT`; the loader only knew `H-1B_DEPENDENT`, so `h1b_dependent` loaded as NULL for every row.
  - `COLUMN_MAP` accepts both spellings, matched exactly (no fuzzy matching). The allowlist is still the personal-data firewall.
  - A file with both spellings is refused.
  - Missing-column messages name every header tried.
- **`N/A` flags.** `WILLFUL_VIOLATOR` / `H_1B_DEPENDENT` carry `N/A` (about 10K cells in FY2026), which counted as bad cells and tripped the 1% bad-cell check.
  - `N/A` / `NA` / `n/a` now load as NULL and are counted per column as `not_applicable`.
  - Anything else unrecognized is still a bad cell.
- **Files aren't all cumulative.** FY2024 Q4 and FY2025 Q4 each hold one quarter; FY2026 Q3 is the year to date.
  - Every load (dry run included) prints the `DECISION_DATE` range and cases per month.
  - It warns about cases decided outside `--fiscal-year`. Above 1% it refuses, writing nothing, unless `--allow-outside-fy`.
  - New view `v_lca_coverage`: per fiscal year, `n_cases`, min/max decision date and months with decisions.
- **Docs.** Every "cumulative within a fiscal year" claim is corrected to the new rule: load every quarterly file for each fiscal year, oldest first; overlaps are upserted on `case_number`.
  - README step 1 lists the 3-FY download set; steps 2–3 explain the coverage output and `v_lca_coverage`.
  - A caveat notes that a partial current FY makes the window uneven.
  - Comments and docs now spell the status `Certified - Withdrawn`, with no SQL logic change.

## Testing

- `pytest` with `TEST_DATABASE_URL`: 553 → **577 passed**, 1 skipped.
- `ruff check .` / `ruff format --check .` (0.17.2) clean; alembic round trip clean; `make views` applies 17 views, twice.
- Synthetic .xlsx and .csv files only, with FAKE employers. The tests cover:
  - both header spellings, and both at once
  - the personal-data columns, still never stored
  - Yes / No / N/A / blank in all three flag columns, with 0 bad cells
  - a two-quarter, two-file coverage fixture checked against `v_lca_coverage`
  - the guard at exactly 1% (warns) and above it (refuses, dry run too; nothing written), and the override
  - the CLI's exit code and output
- No LCA file was downloaded or loaded; no network call except to GitHub.

## Open questions

10 parked decisions are in `docs/overnight-lca-loader-fix.md`, each with the default that was built. Among them: the 1% threshold, `N/A` as NULL, whether Report 3's Methods should cite `v_lca_coverage`, and the uneven 3-FY window.

## After merging

`docs/overnight-lca-loader-fix.md` has the laptop steps: `apply_views.py`, download FY2024 and FY2025 Q1–Q3, dry-run and then load every file oldest first, check `v_lca_coverage` (12 / 12 / 9 months), then `apply_cleaning --only companies visa` and re-render Report 3.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

</details>
