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

---

## Investigation #2 — Commercial vs federal skill demand

**Question asked**: what skills / skill-categories do commercial (Adzuna) analyst
postings emphasize vs federal (USAJobs in-scope) analytics postings — and how much of
any gap is real vs a measurement artifact?

**Outcome**: a positive finding, unlike #1's refusal — the two markets want measurably
different things, and the contrast holds after normalizing out the ~13x text-volume
confound between sources (federal descriptions run full-length; Adzuna's cap
truncates to ~500 chars).

### Shipped artifacts

- `sql/views/v_skill_category_composition.sql` — **source of truth.** Share of each
  source's skill tags per taxonomy category (`workflow`, `bi_tool`, `language`,
  `ml_stats`, `database`, `cloud`, `data_tool`), counts alongside every share.
- `sql/views/v_skill_top_by_source.sql` — the skill-level drill-down, deliberately
  **unfiltered** by minimum n (mirrors `v_commercial_salary_clean` leaving
  `salary_is_predicted` unfiltered in #1) — the reporting floor (n≥5 federal / n≥15
  commercial) is a consumer decision, not baked into the view.
- `docs/findings_commercial_vs_federal_skills.md` — taxonomy-provenance seam
  (which skills were added *this investigation*, fitted to federal vocabulary), the
  symmetric-truncation caveat, and the full Statistics-tag circularity table.
- Artifact: grouped-bar category-composition chart as the primary visual (counts
  labelled on every bar), the skill drill-down rendered as plain subordinate tables —
  deliberately not chart marks, so it can't be mistaken for a claim at the same
  confidence as the composition contrast — plus 3 honest sentences.

### Prep that made the investigation valid — two "built but never run" bugs

- **Series-code ingest** (`JobCategoryCode` 1560/1515/1530) existed in
  `src/ingestion/ingest_usajobs.py` and was documented in `data_dictionary.md`, but had
  only ever been dry-run probed, never executed for real. Running it grew federal
  in-scope **28 → 70**: Data Science (24) and Statistics (5) categories went from zero
  to populated; Operations Research grew 14 → 27. Roughly halved the confidence-interval
  width the investigation was working under.
- **Taxonomy gaps**, found by a targeted spot-check of federal description text and
  closed precision-first (trap test written and confirmed failing *before* each
  pattern was added): SQL gained a `"structured query language"` alias — federal
  postings spell it out where commercial ones say "SQL," so this word was previously
  silently untagged, a wrong number rather than a caveat. Four new skills: SPSS, SSIS,
  SSRS (case-sensitive, low collision risk) and GIS (context-anchored around ArcGIS /
  "Geographic Information System(s)" / anchored bare "GIS," specifically built to reject
  unrelated-acronym reuse like "Global Information Security (GIS)"). Taxonomy 66 → 70
  skills; 160 tests pass / 22 skip, no regressions. **These additions were fitted to
  observed federal vocabulary** — the methods doc records that provenance so a reader
  can see the instrument was partly tuned to one side of the comparison.
- Both bugs were silent — no error, just a capability the project believed it had.
  Flagged as **a candidate seams audit before Phase 6**: check other "we have this"
  assumptions (is scheduling actually running? do snapshots actually accumulate daily?).

### Key numbers (confidence ≥ 0.8)

| Category | Commercial n / % (n=1,483 jobs) | Federal n / % (n=70 jobs) |
|---|---|---|
| workflow | 180 / 33.8% | 26 / 11.0% |
| bi_tool | 122 / 22.9% | 37 / 15.7% |
| language | 99 / 18.6% | 66 / 28.0% |
| ml_stats | 82 / 15.4% | 92 / 39.0% |
| database | 20 / 3.8% | 9 / 3.8% |
| cloud | 20 / 3.8% | 3 / 1.3% |
| data_tool | 10 / 1.9% | 3 / 1.3% |

Commercial skews **workflow + bi_tool** (56.7% combined); federal skews
**ml_stats + language** (67.0% combined). This is a composition contrast (share of
each source's own tags), not a raw-rate comparison — the latter would just measure
which source has more text.

**Federal Statistics tag — validated non-circular.** 75.7% of federal in-scope jobs
carry a Statistics tag overall, but the rate holds at 92.6% (25/27) within the
Operations Research series specifically — a bucket admitted by occupational-series
code, not any statistics-related label — nearly matching the Statistics/Data-Science
series' own 93.1% (27/29). It collapses to 7.1% (1/14) in the skill-density-admitted
slice. Reported as **concentrated in the 56 series-identified jobs**, not a flat claim
across all 70.

**Truncation cost, kept as a demonstration, not a correction.** Federal loses ~70x its
skill density when its full text is cut to Adzuna's ~500-char cap and re-extracted
(2.5 → 0.036 tags/job) — because federal's first 500 characters are `JobSummary`
mission prose, not a requirements list. This was the basis for **dropping** the
originally-planned truncation-matched (commercial-500-vs-federal-500) comparison:
equal character count isn't equal content, so it doesn't control for anything.

### Guardrails carried forward

- Commercial's own composition is **also** subject to placement/truncation — its
  native ~500-char text may be front-load-inflated on workflow/bi_tool and
  back-load-suppressed on language/ml_stats by the same mechanism that hurts federal.
  This seam is symmetric; only federal's side has been separately measured (the 70x).
- Skill-level drill-down (n≥5 federal / n≥15 commercial) is directional texture, never
  presented at the same confidence as the composition contrast. Every rate ships with
  its count inline — no federal percentage without its n beside it.
- Federal's measured skill mix is partly a function of taxonomy work done *to find it*
  this investigation — see the provenance table in `findings_commercial_vs_federal_skills.md`.

### Open threads after #2

1. **Skill co-occurrence / role clustering** — previously data-starved to attempt.
   Federal at n=70 / 3.37 tags/job is the first population where within-source
   co-occurrence is worth a look, though still thin for genuine clustering.
2. **Disclosure-selection** (parked from #1) — still open, still wants a full-text
   commercial source this project doesn't have yet. Arguably the sharpest unasked
   question in Phase 3 so far.
3. **Seams audit** — a deliberate pass over other "we have this" claims in the project
   (scheduling, daily snapshot accumulation, anything assumed-running-but-unverified)
   before Phase 6, prompted by finding two of them this investigation.
