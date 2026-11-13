# Phase 2 log (`claude/portfolio-next`)

One entry per run, newest first. The backlog is `docs/dev-log/next-backlog.md`.

## 2026-11-13: fourth Phase 2 run

- **Branch:** `claude/portfolio-next`; main is still at 2f80d85, so there was nothing to merge.
- **Starting head:** 5362ff6. The pre-commit script was green on it; CI was green on its last three
  pushes.
- **Review-load brake:** 26 commits were not in main at the start, so this run did Tier 1 work only.
- **Finished:** N10, a re-review of the Part B publish path (`src/reports/publish.py`,
  `src/reports/__main__.py`, `src/reports/provenance.py`), which the N1 review had not covered.
- **Commits:** the N10 commit that carries this entry.
- **pytest:** 895 passed, 1 skipped before; 897 passed, 1 skipped after.

### N10: findings and fixes

1. **A second publish was stamped "-dirty".** The provenance commit is marked "-dirty" when any tracked
   file has uncommitted changes. The first `--publish` rewrites the tracked README.md (and, once a
   report is committed, its `docs/reports/<slug>/` files), so the owner's documented loop, "read every
   stale-number warning, fix the narrative, publish again", produced a published report whose stamp
   said the code differed from its commit when it did not. `git_commit` now takes paths to leave out,
   and `--publish` leaves out `docs/reports` and `README.md`, the files it writes itself. A plain render
   behaves as before. Two new tests fail before the fix: one on a throwaway git repository, one that
   publish passes those paths.
2. **Owner step 1 named the wrong view count once this branch is merged.** It said "25 views applied";
   with `v_analysis_population` from N2 the count is 26. The step now names both.

Checked and left as they are: the merge of narrative into placeholder blocks, the refusal paths, the
stale-number regexes against the renderers' formats (`<0.1%`, `$85,000`, `$85k`, ranges with an en
dash), the README block for 0, 1 and 2 reports, and that the CLI catches a guardrail failure during
publish.

### Next run

Commits not in main after this run: 27. The brake still applies: Tier 1 fixes only until the owner
merges. Open items N7, N8 and N9 wait for the merge.

## 2026-11-13: third Phase 2 run

- **Branch:** `claude/portfolio-next`; main is still at 2f80d85, so there was nothing to merge.
- **Starting head:** 0d02430. The pre-commit script was green on it; CI was green on its last three
  pushes (`gh run list`).
- **Finished:** N6. CI now runs `python scripts/apply_views.py` twice on the alembic-built database,
  after the migration round trip and before the tests, as the local pre-commit script does
  (`make views` twice). README's status table and `docs/PROJECT_GUIDE.md` now list the step.
- **Commits:** the N6 commit that carries this entry.
- **pytest:** 895 passed, 1 skipped before and after (no tests added; the change is CI only).

### Next run

Commits not in main after this run: 26, above the review-load brake of 25. The owner has been
asked to review and merge. Until main catches up, runs do Tier 1 work only (fixes to what exists).
Open items N7, N8 and N9 wait for the merge.

## 2026-11-13: second Phase 2 run

- **Branch:** `claude/portfolio-next`; main is still at 2f80d85, so there was nothing to merge.
- **Starting head:** 10ebf19. The pre-commit script was green on it before any change.
- **Finished:** N4 (G3, the demo-dashboard screenshot) and N5 (docs-consistency test).
- **Commits:** 37ac0f7 (N4), then the N5 commit that carries this update.
- **pytest:** 862 passed, 1 skipped before; 862 passed, 1 skipped after N4 (no tests added);
  895 passed, 1 skipped after N5.

### N4: G3, one honest screenshot

- Local Docker ran the pinned `metabase/metabase:v0.64.3.4`. The demo dataset was built in
  `jobmarket_demo` with `scripts/seed_demo_data.py --full`, the 26 views applied, the reader role
  granted, and `python -m src.dashboard.provision` built all six dashboards (Metabase's application
  database lived inside the throwaway container; nothing from it is committed).
- The Market overview dashboard was captured with the pre-installed headless Chromium to
  `docs/img/dashboard-demo.png` (2128 x 1536, 2x scale). The image shows the dashboard's own banner,
  "DEMO DATA: synthetic, not market findings", and the README adds a caption line saying it is
  synthetic demo data.
- The capture stops above the seniority and top-employers tables. The demo seed reuses employer names
  from the Adzuna fixtures, so that table pairs real employer names with invented counts; the crop keeps
  them out of the image. `docs/dashboard.md` says how the image was made and that it should be replaced
  by a capture of the real dashboards after the server cut-over.
- The image was looked at before committing.

### N5: docs-consistency test

- `tests/test_docs_consistency.py` (no database): every `sql/views/` file has its own heading or
  table row in `docs/data_dictionary.md`; every `make <target>` shown as a command in README.md or
  docs/ (outside the work logs in docs/dev-log/, which stay as written) is a Makefile target; every
  relative link and image in README.md and docs/ resolves. Three small tests cover the parsing helpers.
- The view check failed before this commit for four views that were only mentioned in passing:
  `v_commercial_salary_clean`, `v_field_completeness`, `v_skill_category_composition` and
  `v_skill_top_by_source`. Each now has an entry under a new "Phase 3 analysis views" section of
  `docs/data_dictionary.md`, built from the view's SQL and header (columns from
  `information_schema` on the demo database). No view changed.
- The make check, run over the work logs too, flagged `make isn` and `make prod-` in two old logs:
  prose fragments, not commands. That is why the logs are left out of that check.

### Next run

Commits not in main after this run: 25. The review-load brake applies above 25, so the next run may
add at most one more commit; after that only Tier 1 fixes until the owner merges. Recommended next
item: N6 (CI applies the views twice), which is a one-commit change.

## 2026-11-13: first Phase 2 run

- **Branch:** `claude/portfolio-next`, created from the head of `claude/portfolio-readiness`
  (3c8fad7). main is still at 2f80d85, so there was nothing to merge.
- **pytest before:** 835 passed, 1 skipped (the Metabase end-to-end test, which needs METABASE_URL).
  The pre-commit script was green on the starting head; CI on `claude/portfolio-readiness` was
  green through its last commit.
- **Finished:** N1 (verification and review, with three fixes) and N2 (G1).
- **Commits:** 6ea466c (N1 fixes), then the N2 commit that carries this log.
- **pytest after:** 837 passed, 1 skipped after N1; 862 passed, 1 skipped after N2.

### N1: acceptance criteria re-checked on the head, from scratch

| # | Criterion | Result |
|---|---|---|
| 1 | A: engine reuse, skills convergence, remote full text | Pass: `tests/test_db_engines.py`, `tests/test_extract_skills_converge.py`, `tests/test_remote_full_text.py` all green; the reviewer read `extract_skills.py` and `apply_cleaning.py` and found them correct |
| 2 | B: init and publish through the test-only override; refusals and stale-number warning tested; README block for 0/1/2 reports; nothing published committed | Pass: `tests/test_report_publish.py` green; `git diff main --name-only` has no `docs/reports/` file and no `narrative.md` |
| 3 | C: README order, no `YOUR_USERNAME`, spaCy/Prefect lines, no `docs/overnight-` path, LICENSE | Pass: `git grep` checks as in the brief; spaCy/Prefect match only three lines that say planned, deferred or not used |
| 4 | D: three views apply in order and are tested; sort-by unset sends the old parameters; methods note; doctor check | Pass. Fix made: see "doctor check 11" below |
| 5 | E: reference equality and statement counts | Pass: both tests green |
| 6 | F: shortlist on the demo database with the example profile; refuses a tracked directory | Pass: 69 entries on the demo seed; `--out docs` refused with exit 2; missing profile exits 2 with the copy command. Two fixes made, below |
| 8 | Every commit green; one alembic head; views apply twice | Pass: 25 views before N2, 26 after |
| 9 | Nothing real, nothing in the owner's voice | Pass: no data, log, .env, uv.lock, aliases, narrative or published report in `git diff main --name-only`; no `@gmail` or `C:\Users\<name>` added |

Comments-only check: the Phase 1 edits to the existing views `v_employer_sponsorship`,
`v_job_visa_outlook` and `v_field_completeness` change comment lines only.

All relative links in README.md and docs/ resolve, and every make target the docs name exists.
One gap, carried to N5: `v_skill_top_by_source` has no entry in `docs/data_dictionary.md` (it had none on main either).

### N1: review findings and fixes

An independent review read the Phase 1 diffs of the shortlist, cleaning, snapshot views, doctor
check and sort-by change. The four findings were checked against the code. Three were real and are fixed:

1. **Doctor check 11 got slower as history grew.** It found the latest day per source with a correlated
   subquery over `v_search_window_coverage`, which re-ran the view for every row. On 100 synthetic days
   (4,000 stored pages) the old query took 4.1 s and the new one 13 ms, with the same 8 rows. Now
   the latest day is computed once and joined. The existing database test covers the result; a wall-clock
   test was not added (the brief forbids them).
2. **`include_no_seniority_signal = false` did nothing unless `seniority` listed levels.** The example
   profile and `docs/shortlist.md` say no-signal postings are kept "unless include_no_seniority_signal =
   false", with no condition. The code now matches the docs. New test
   `test_no_signal_rule_applies_without_a_seniority_list` fails before the fix.
3. **Postings with no employer were merged with each other** when their titles matched, which lost every
   link but the newest. Now each one stays separate. New test
   `test_postings_without_an_employer_are_never_merged` fails before the fix.

The fourth finding (visa bucket for uncleaned rows) only shows up if the shortlist runs before
cleaning has. It is recorded in the backlog notes; no code was changed for it.

### N2: G1, one definition of the analysis population

- New view `v_analysis_population` (`job_id`, `market`), sorting before its readers.
- 11 views now read it instead of repeating the filter. Verbatim copies of their earlier files are
  in `tests/fixtures/analysis_population_reference/`. `tests/test_analysis_population.py` runs each
  reference query and the current view on the full demo seed and on hand-built edge rows. Each pair
  must have the same column names, the same column types and the same rows. The edge rows cover
  in_scope true, false and NULL on both sources, a source outside the population, a job with no
  company, links either side of the 0.8 floor, and snapshot gaps.
- Mutation check: changing the population filter makes 9 of the edge-row comparisons fail.
- Single-market views keep their own filters (Q12).
- Documented in `docs/data_dictionary.md`.

### Not done

- G2 (N3) parked: 63ea064 is still not in main, so `register_daily_task.ps1` is untouched.

### Next run

Commits not in main after this run: 23. The review-load brake applies above 25, so the next run can
add two commits before it must stop and ask the owner to review. Recommended order: N5 (docs-consistency
test, which also adds the missing `v_skill_top_by_source` entry), then N6 (CI applies the views twice).
