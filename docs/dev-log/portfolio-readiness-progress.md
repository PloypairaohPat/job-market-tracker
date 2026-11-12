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

## Latest test count

764 passed, 1 skipped (after B).

## Parked questions

| Q | Part | Question | Default built |
|---|---|---|---|
| Q1 | A2 | Should `sync_taxonomy` delete `skills` rows that left the taxonomy? | No: keep the row, log how many are orphaned |
| Q2 | A3 | Should federal remote become a reported rate once the owner has checked a sample on real data? | No change now; Report 2 keeps "not measurable" |
| Q3 | B | Should `--publish` refuse when `sql/views/` or `src/reports/` has uncommitted changes? | Warn, don't refuse |
| Q4 | B | Should published reports also be exported as HTML or PDF? | Not built; Markdown only |

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
