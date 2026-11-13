# Phase 2 backlog (`claude/portfolio-next`)

A ranked list of follow-up work after the portfolio-readiness brief
(`docs/dev-log/portfolio-readiness.md`). Tiers follow the Phase 2 rules: verify what shipped, then
Part G, then tests and CI, then the owner's own steps, then deliberately unbuilt features, then
code health. Each run takes the highest-ranked open item. The run-by-run record is
`docs/dev-log/next-log.md`.

Status values: open, in progress, done (commit), parked (reason).

| Id | Tier | Item | Why, and for whom | Evidence | Size | Status |
|---|---|---|---|---|---|---|
| N1 | 1 | Re-check the brief's acceptance criteria on the head, and review the Phase 1 diffs as an outside reviewer | Correctness: Phase 1 shipped 5,000+ lines in one pass | `git diff main`; the review results are in next-log.md | M | done (6ea466c) |
| N2 | 2 | G1: `v_analysis_population`, read by every view that compared the two markets with an inline filter | Correctness and maintainability: 11 views repeated the population filter | `grep -l usajobs sql/views/*.sql` | M | done (N2 commit) |
| N3 | 2 | G2: wake-to-run in `scripts/windows/register_daily_task.ps1` | Owner: the laptop clock has missed days | The brief allows it only once 63ea064 (`claude/battery-fix`) is in main | S | parked: 63ea064 is not in main; the file is untouched until the owner merges that branch |
| N4 | 2 | G3: one honest demo-dashboard screenshot at `docs/img/dashboard-demo.png` | Recruiter: the repo tracks no image of a dashboard | `git ls-files` lists no .png | M | done (N4 commit): `docs/img/dashboard-demo.png`, embedded in README.md with a synthetic-data caption |
| N5 | 3 | A docs-consistency test: every `sql/views/` file described in `docs/data_dictionary.md`, every make target the README names exists, every relative link in README.md and docs/ resolves | Correctness of docs; recruiter trust | `v_skill_top_by_source` has no entry in `docs/data_dictionary.md` (true on main too) | S | open |
| N6 | 3 | CI runs `scripts/apply_views.py` twice on the alembic-built database, as the pre-commit script does | Correctness: a view that fails on re-apply would pass CI today | `.github/workflows/ci.yml` has the round trip but never applies the views | S | open |
| N7 | 3 | Measure coverage locally (not added to pyproject) and test untested behaviour in cleaning, visa, reports and shortlist | Correctness | to be measured | M | open |
| N8 | 4 | One command that builds a demo database, applies the views and renders every report; README quick start | Recruiter and owner: today it takes five commands | README "Run it yourself" | M | open |
| N9 | 4 | Read-only pre-flight for publishing a report (narrative present and complete, database not demo, README block present) before the owner starts | Owner | `src/reports/publish.py` reports problems only at publish time | S | open |

## Notes from the N1 review

- Shortlist visa bucket before cleaning: `v_job_visa_outlook` holds in-scope jobs only, so a
  commercial posting whose `in_scope` is still NULL (ingested but not yet cleaned) shows the
  bucket `unknown` in the shortlist. The daily runner cleans before anyone runs the shortlist,
  and cleaning marks every Adzuna row in scope, so this needs an out-of-order manual run.
  No change made; recorded here in case the owner wants the shortlist to refuse uncleaned rows.

## Parked questions

Questions Q1 to Q11 from Phase 1 are in `docs/dev-log/portfolio-readiness.md` and still stand.

| Q | Question | Options | Recommendation |
|---|---|---|---|
| Q12 | Should the single-market views (`v_commercial_salary_clean`, `v_salary_population`, `v_federal_skill_by_admission`, `v_field_completeness`, `v_field_completeness_counts`) also read `v_analysis_population`? | (a) leave their one-market filters [built]; (b) join the population view and filter on `market` | (a): they add one-market conditions of their own, and the brief's G1 targets the shared two-market definition |
