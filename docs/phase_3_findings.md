# Phase 3 Findings

Analyses live as views (`sql/views/`, source of truth) plus a findings entry here per
investigation. Same discipline as `phase_1_findings.md`: record what worked, what the
data refused to support, and what carries forward — don't let the reasoning live only
in chat history.

---

## Investigation #1 — Salary premium by skill (commercial)

**Question asked**: does mentioning a given skill (SQL, Tableau, Python, ...) correlate
with a higher salary in commercial (Adzuna) data-analyst postings?

**What shipped instead**: "What commercial postings actually pay" — the clean data
refused the skill-premium framing at the population's own evidentiary bar. That refusal,
documented rather than patched around, is the finding. Same "analytics is judgment under
ambiguity" beat `phase_1_findings.md` called out ahead of schedule in Phase 1.

### Shipped artifacts

- `sql/views/v_commercial_salary_clean.sql` — **source of truth.** One row per clean
  commercial job (`source='adzuna'`, `salary_quality='ok'`, USD, `period='year'`),
  exposing `salary_midpoint = (salary_min+salary_max)/2`, `salary_is_predicted` (left
  **unfiltered** — both the disclosed cut and the predicted-vs-disclosed comparison read
  from the same view), `seniority`, `metro_area`. Materialized and re-queried to confirm
  no drift from recon numbers.
- `docs/findings_skill_premium_deferred.md` — the 10 candidate skills, why the cut is
  deferred, unblock conditions (including the selection caveat below).
- Artifact page (disclosed anchor stat, predicted-vs-disclosed comparison, seniority box
  chart, 3-sentence finding). Headline numbers use disclosed only; predicted appears
  exactly once, explicitly labeled, as a comparison — never pooled silently.

### Key numbers (commercial · `'ok'` · USD · `year` · midpoint)

| Population | n | median | IQR |
|---|---|---|---|
| Full `'ok'` (100% USD, 100% year) | 1,481 | — | — |
| Disclosed (`salary_is_predicted=false`) | 178 | **$98,500** | $87,013–$111,425 |
| Predicted (`salary_is_predicted=true`) | 1,303 | $104,197 | $84.0K–$124.5K |

Predicted runs ~$5.7K higher than disclosed at the median. Adzuna always returns a
salary — its model backfills undisclosed figures — which is *why* `salary_is_predicted`
exists; the 100%-have-salary rate is API behavior, not a data-quality signal.

Seniority within disclosed (n=178): NULL=110 (excluded — NULL means no title signal,
never coerced to "mid"), senior=57 (**the only band clearing n≥15**), lead=5, mid=3,
junior=3.

### Why skill-premium wasn't answerable on clean data

- The disclosed set is too sparsely tagged: at confidence≥0.8, 34/178 (19.1%) carry any
  skill tag; the single most-common skill reaches n=3; **zero skills clear n≥15**.
- The full `'ok'` pool (disclosed + predicted) does clear n≥15 for 10 skills, but
  building a per-skill chart from it was rejected on two independent grounds: (a)
  pooling predicted salaries makes every premium partly reflect Adzuna's own salary
  model, and the disclosed set is too thin to cross-check that circularity; (b) skill
  counts are truncation-floored (Adzuna's 500-char description cap), so the *ranking*
  itself is distorted — Python landing at n=17 is plausibly a truncation artifact, not
  a true low-demand signal.
- The 10 candidates, for when it unblocks (confidence≥0.8, full `'ok'` pool,
  truncation-floored — not to be reported as premiums): SQL 72, ETL 64, Tableau 56,
  Agile 48, Data Governance 46, Experimentation 44, Power BI 42, Excel 19, Statistics
  19, Python 17.

### Why disclosed ≠ predicted (selection-bias thread — evidence, not proof)

Length was ruled out as the explanation: both subsets sit at ~500 chars median/mean —
identically truncated — so the 19.1% vs 45.2% skill-tag-rate gap (26pp) between
disclosed and predicted is compositional, not a length artifact.

Two same-direction contributors were found, both **partial** — neither closes the 26pp
gap on its own:

1. **Front-loading.** Disclosed postings are ~2.4x as likely to spend their first 500
   characters on comp/benefits/EEO text (either-pattern match: 16.3% vs 6.8%) — but the
   9.5pp incidence gap is smaller than the 26pp tag-rate gap.
2. **Metro skew.** Disclosed skews toward disclosure-law metros: SF Bay Area 3.9% vs
   1.1% for predicted (**n=7/178 — directional only, do not treat as quantitative**);
   lower NULL-metro rate overall (84.8% vs 92.1%).

Honest statement: disclosed salaries **skew toward** comp-forward text and
disclosure-law metros, which **partially explains** the gap; a residual is
**unexplained**. This is *not* "disclosed is a clean pay-transparency subpopulation,
full stop" — the causal chain (comp text eats the skill budget; disclosure law drives
who discloses) is an **inferred hypothesis**. Phase 5 must not cite it as proven.

### Open threads

1. **Skill premiums — deferred.** Cleaner unblock: a full-text description source
   (Greenhouse/Lever ATS pages or similar) that defeats front-loading truncation
   directly, regardless of whether a given posting happens to lead with comp text —
   and doesn't inherit the disclosure-law-metro skew, since it isn't filtered to
   whichever jobs happened to disclose salary. Weaker unblock: accumulate disclosed
   Adzuna volume until some skill reaches n≥15 — but that only makes a number
   *reportable*, not *representative*; the result describes "premium among jobs that
   disclose," and that scope has to stay in the headline, not a footnote.
2. **Disclosure-selection — candidate for its own Phase 5 piece** ("who discloses
   salary, and how that biases what we can measure"). Don't bolt it onto the
   "what commercial postings pay" artifact — it deserves its own frame, and gets
   sharper once a full-text source breaks the truncation confound and disclosed volume
   is enough to go from directional to quantitative.

### Guardrails carried forward

- Salary population: `WHERE salary_quality='ok' AND salary_currency='USD' AND
  salary_period='year'`. Keep `salary_is_predicted` separable — never pool silently.
  `midpoint=(salary_min+salary_max)/2`; report **median**, not mean (right-skewed); always
  alongside IQR.
- Adzuna skill rates are truncation-floored — never present as complete recall; a low
  rank may be a truncation artifact, not a true demand signal.
- Multiples computed on a tiny count (e.g. the metro 3.5x on n=7) always carry the raw
  n inline — a ratio without its denominator misleads.
- Federal (USAJobs) stays deferred for salary-by-skill: n=28 in-scope (see
  `data_dictionary.md`'s `jobs.in_scope` section), GS bands not comparable to
  commercial figures. Time-series salary analysis is still unanswerable — no
  snapshot history has accumulated yet.
