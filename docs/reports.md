# Reports (Phase 5)

The written reports are the portfolio centerpiece. The report kit turns the SQL views into a report's tables, charts and methods section with one command, so a report can be regenerated whenever the data grows. You write only the narrative.

Laptop commands below are for Windows PowerShell with `uv`, run from the repo root, as in [`docs/daily-operation.md`](daily-operation.md).

## The reports

| Slug | Report | Regenerates | Views read |
|---|---|---|---|
| `commercial-vs-federal-skills` | Commercial vs federal skill demand | Phase 3 Investigation #2 | `v_skill_category_composition`, `v_skill_category_composition_roles` (a distinct-roles sensitivity table), `v_skill_text_basis`, `v_skill_top_by_source`, `v_federal_skill_by_admission` |
| `how-much-employers-disclose` | How much employers disclose | Phase 3 Investigation #3 | `v_field_completeness`, `v_field_completeness_counts` |
| `what-postings-pay` | What commercial data-analyst postings pay | Phase 3 Investigation #1 | `v_commercial_salary_clean`, `v_salary_population`, `v_salary_skill_coverage`, `v_ingestion_daily` |
| `employers-and-sponsorship` | Who hires data analysts, and who has filed to sponsor them | new: hiring concentration (postings and distinct roles) and the employers' LCA filing record (visa layer) | `v_employer_postings`, `v_employer_roles`, `v_employer_sponsorship_match`, `v_visa_outlook_summary`, `v_matched_employer_lca_wages`, `v_lca_coverage`, `v_lca_monthly` |

`uv run python -m src.reports --list` prints the current list.

## Rendering a report

### On the laptop

```powershell
uv run python scripts/apply_views.py                          # once after pulling: reports add views
uv run python -m src.reports commercial-vs-federal-skills     # or: make report REPORT=commercial-vs-federal-skills
```

It writes `reports\commercial-vs-federal-skills\report.md` and its chart(s), `composition.png`, next to it. Open the `.md` in VS Code's Markdown preview (Ctrl+Shift+V).

- `reports\` is **gitignored** and overwritten on every run. Publishing (below) is how a report enters the repo.
- `--out <folder>` writes somewhere else.
- It reads `DATABASE_URL` from `.env`, like every other command.

### On the server

After the cut-over the data lives on the server ([`docs/deploy.md`](deploy.md)). After pulling, rebuild the image and apply the views once, then render:

```bash
cd ~/job-market-tracker
git pull
make prod-build                                   # the image must contain the report code
make prod-views                                   # the views the reports added
make prod-report REPORT=commercial-vs-federal-skills
```

`make prod-report` runs the report inside the pipeline image against the stack's database, as you (so the files are yours), and writes `~/job-market-tracker/reports/<slug>/`. Copy the folder to the laptop to read it:

```powershell
scp -r deploy@203.0.113.10:job-market-tracker/reports/commercial-vs-federal-skills $HOME\jobmarket-reports\
```

The image has no `.git`, so the provenance stamp's commit is the server checkout's, marked "(host checkout)". It matches the code only if you ran `make prod-build` after your last `git pull`.

## What a rendered report contains

1. **Provenance stamp** at the top:
   - database name
   - generation time (UTC)
   - git commit
   - the row count of every view the report read
2. **Demo banner.** If the database name contains `demo` or `test`, a banner reads **"Synthetic demo data, not market findings."** above the title and in every chart title.
3. **Tables and charts**, all from the views.
4. **Methods and caveats**, generated from the data and the guardrails.
5. **Narrative placeholders** marked `[TO WRITE: ...]`: headline, what it means, what to do about it. Each lists the numbers from this run to draw on. A published report has your narrative in their place (below).

The kit writes no conclusions: those are yours.

## Writing the narrative

The narrative lives in `docs\reports\<slug>\narrative.md`, one `##` section per placeholder (Headline, What it means, What to do about it). You write it and commit it; the kit merges it into the report when you publish. The rendered file under `reports\` is still overwritten on every run, so don't write in it.

Four steps, shown for `employers-and-sponsorship`. Run them from the repo root, with `DATABASE_URL` in `.env` pointing at the real database.

**1. Init.** Create the narrative file (it is never overwritten if it exists):

```powershell
uv run python -m src.reports employers-and-sponsorship --init-narrative
```

Each section starts with an HTML comment saying what it is for and where its numbers are. Comments are dropped when publishing, so you can leave them.

**2. Write.** Render the report to see this run's numbers, then write each section in the narrative file:

```powershell
uv run python -m src.reports employers-and-sponsorship
code reports\employers-and-sponsorship\report.md
code docs\reports\employers-and-sponsorship\narrative.md
```

The list under each `[TO WRITE: ...]` block in the render is this run's numbers, with their n and denominators. Quote them as they are.

**3. Publish.** Render with the narrative merged in:

```powershell
uv run python -m src.reports employers-and-sponsorship --publish
```

It writes `docs\reports\employers-and-sponsorship\report.md` and its PNGs (tracked by git, unlike `reports\`), keeps the provenance stamp at the top, leaves out the "numbers from this run" lists, and refreshes the published-reports block in `README.md`. It refuses, naming the reason, when:

- the database name contains `demo` or `test`: synthetic numbers are never published as findings
- `narrative.md` is missing, a section is missing or empty (or holds only the init comment), or the text still contains `TO WRITE`
- any guardrail fails, as in a normal render. For Report 3 that includes the narrative: a paragraph about sponsorship (LCA, H-1B, visa, filing, sponsor) may not name an employer from the top-employers tables, and the sponsorship wording rules apply to your text too. For Report 4 the salary wording rule does.

It warns, without refusing, about every percentage or dollar figure in the narrative that this run's render doesn't contain, with its line number in `narrative.md`. That usually means the narrative quotes an older run: check each one. It also warns when `sql\views\` or `src\reports\` has uncommitted changes, because the provenance commit then doesn't describe the code that rendered the report.

**4. Commit.** Read the published file, then commit the folder and the README:

```powershell
code docs\reports\employers-and-sponsorship\report.md
git add docs\reports\employers-and-sponsorship README.md
git commit -m "Publish: employers and sponsorship"
git push
```

When the data has grown, publish again and read the warnings: they list the narrative's figures that moved.

`uv run python -m src.reports --index` refreshes only the README block (for example after deleting a published report).

## Guardrails (enforced by code)

A report can't print a number except through `src/reports/guardrails.py`, and the Markdown and chart renderers refuse anything else. Each rule comes from a "Guardrails carried forward" list in [`docs/phase_3_findings.md`](phase_3_findings.md), and each has a unit test.

| Rule | What the code does |
|---|---|
| Every grouped number shows its n | Table cells accept counts, labels and guardrail types only. A float, or a label that's really a number ("33.8%"), is refused. Medians and lengths render as "235 (IQR 224–244; n=609)". |
| No rate without its denominator | A `Rate` can't be built without one, and renders as "33.8% (180 of 533 tags)". When the view computed the percentage, the numerator and denominator must reproduce it, or the report stops ("wrong denominator?"). A gap is "+22.8 pp" only in a table row that shows both rates. |
| Salary | Only `salary_quality = 'ok'`, USD, `period = year` (`v_commercial_salary_clean`, or rows that prove it). Median and IQR, never the mean: `check_salary_wording` refuses "mean", "average" or "avg" in report 4's text, except in the one Methods sentence on why the median is used. Employer-disclosed and Adzuna-predicted are summarized separately; there is no pooled option. |
| Salary floor and differences | `SALARY_FLOOR = 15`: a salary group under it shows its n, and its median is withheld with the reason (`FlooredSalary`). `SalaryDiff`, the dollar counterpart of a gap, is built only from two summaries of different bases (or one basis, two groups), renders the signed difference with both medians and both n, and is refused below the floor or at n = 0. A salary box chart draws one summary per box, only at n ≥ 15, with no single posting shown. |
| Small groups | Skill drill-downs keep only n ≥ 15 (commercial) and n ≥ 5 (federal), and say how many rows were suppressed. Composition categories below those floors are shown but marked ‡. |
| Truncation | Commercial (Adzuna) skill rates are marked truncation-floored, and a table or chart showing one must say "truncation-floored". |
| Instrument-limited fields | In report 2, seniority, metro and remote get their own section with the mechanism that limits each, and can't be charted beside the measured fields. Federal remote is "not measurable", never a 0% rate. |
| LCA filings (report 3) | `src/reports/lca_guardrails.py`: a filing count must say it counts LCA filings and can't be called hires or approvals; the offered wage is "on LCA filings", never what postings pay. Unmatched employers are "no match found", "unknown" is never "no", and text claiming an employer doesn't sponsor is refused. Methods must print the caveats from `src/visa/README.md`. Views and frames must be aggregate (no job ids, titles, URLs or case numbers), so the private Visa outlook dashboard isn't recreated. Without LCA data the sponsorship sections say "LCA data not loaded". |
| Views only | `ViewReader` reads whole `v_*` views defined in `sql/views/`. Base tables and hand-written SQL are refused, and a test checks that no report module talks to the database another way. |

If a report stops with a guardrail error, the message names the rule. It almost always means the data or a view changed shape. Fix the view or the report; don't work around the rule.

## Trying it on demo data

`seed_demo_data.py --full` builds a synthetic dataset in a database whose name contains `demo` or `test` ([`docs/dashboard.md`](dashboard.md)). Point `DATABASE_URL` at it, apply the views, and render: the report carries the demo banner. The demo's numbers mean nothing. For example, its federal market is 5 postings, so every federal skill falls below the n ≥ 5 floor.

## Adding a report

1. **Views first.** If a number isn't in a view, add one under `sql/views/` (header comment, n beside every aggregate), with tests. Then `make views`.
2. **A module** in `src/reports/`, exposing:
   - `SLUG`, `TITLE` and `VIEWS`
   - `compute(frames)`: view frames in, plain data out
   - `SECTIONS`: the narrative sections, heading -> what the section is for
   - `render(data, provenance, out_dir)`: Markdown and PNGs out, every number through the guardrails, narrative as `doc.placeholder(name, SECTIONS[name], numbers)` blocks
   - optionally `check_published(data, sections, text)`: the report's text guardrails, run again over the published text with the narrative merged in
3. **Register it** in `src/reports/catalog.py`.
4. **Tests:** a golden file rendered from hand-built frames (`tests/fixtures/reports/`; regenerate with `UPDATE_GOLDEN=1` and review the diff), plus an end-to-end run on the demo seed.
5. **Document it:** add a row to the table at the top of this page.

What is committed: published reports (`docs/reports/<slug>/`, from the real database, with the owner's narrative) and the golden fixtures (`tests/fixtures/reports/`, from invented numbers). What is never committed: output rendered from a demo or test database, and anything under `reports/`.
