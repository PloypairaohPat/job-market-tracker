# Skill-level salary premium — deferred

**Question**: does mentioning a given skill (SQL, Tableau, Python, ...) correlate
with a higher disclosed salary for commercial (Adzuna) postings?

**Status: deferred.** Not supportable on clean data yet — see reasoning below.
Revisit once the unblock condition is met.

## Why it's deferred

The only trustworthy salary population is disclosed (`salary_is_predicted=false`),
`salary_quality='ok'`, USD, `period='year'` — n=178. Within that population,
skill tagging is too sparse to report anything at the population's own bar of
n≥15 per skill:

- Only 34/178 jobs (19.1%) carry *any* skill tag at confidence≥0.8.
- The single most-common skill (SQL / Data Governance, tied) reaches n=3.
- **Zero skills clear n≥15** in the disclosed population, at either
  confidence≥0.8 or ≥0.9.

The obvious workaround — pool in Adzuna's predicted-salary rows to get volume —
was rejected: predicted rows are Adzuna's own salary model output, not
employer-disclosed figures, and their median ($104,197) differs meaningfully
from disclosed ($98,500). Blending them into a "the" skill premium number would
launder a model estimate into what reads as a market fact.

**Ruled out as the explanation**: description truncation length. Median/mean
`LENGTH(description)` is ~500 chars in *both* the disclosed and predicted
pools — identically truncated. So the 19.1% vs 45.2% skill-tag-rate gap
between disclosed and predicted is not a length artifact; truncation caps
recall for both pools equally.

**The gap is compositional, not a length artifact** — two mechanisms found,
both pointing the same direction, neither alone fully accounting for the
magnitude:

- **Front-loaded comp/benefits/EEO text eats the truncation budget.**
  Within the first 500 characters, disclosed postings match a comp pattern
  (`$`, `salary`, `compensation`, `pay range`, `per year`) at **12.9%** vs
  **5.1%** for predicted, and match benefits/EEO language (`benefits`, `401`,
  `PTO`, `equal opportunity`, `EEO`) at **5.6%** vs **2.4%**. Either pattern:
  **16.3%** disclosed vs **6.8%** predicted — disclosed postings are ~2.4x as
  likely to spend early characters on comp/benefits boilerplate instead of
  role/skill content. Directionally real, but the incidence gap (9.5pp) is
  smaller than the tag-rate gap (26pp), so this is a contributor, not the
  whole mechanism.
- **Disclosed postings skew toward known, higher-disclosure metros.**
  Disclosed jobs have a *lower* NULL-metro rate than predicted (84.8% vs
  92.1%) and land in SF Bay Area at 3.9% vs 1.1% for predicted (~3.5x) —
  consistent with a pay-transparency-law selection effect (CA, NY, WA, IL
  all have salary-disclosure requirements touching this population). **n=178
  disclosed with only 7 SF Bay Area postings — directional, not a claim.**

Net read: disclosed salaries aren't a random sample of commercial postings —
they're skewed toward postings that lead with pay/benefits text and toward
jobs in disclosure-law metros. Both patterns eat into the character budget
available for skill mentions and reflect *who discloses*, not *who has which
skills*.

## The 10 candidate skills (for reference, NOT for reporting as premiums)

Computed against the full `'ok'` population (n=1,481, disclosed + predicted
combined) at confidence≥0.8, purely to show what volume *would* look like if
the population were bigger — this list must not be used to claim a salary
premium, since it mixes modeled and disclosed salary:

| Skill | n (full ok pop, incl. predicted) |
|---|---|
| SQL | 72 |
| ETL | 64 |
| Tableau | 56 |
| Agile | 48 |
| Data Governance | 46 |
| Experimentation | 44 |
| Power BI | 42 |
| Excel | 19 |
| Statistics | 19 |
| Python | 17 |

## Unblock condition

1. **A full-text description source (Greenhouse/Lever ATS pages, or similar)
   for commercial postings — the cleaner unblock.** Removing the ~500-char
   Adzuna truncation floor defeats front-loading regardless of whether a
   given posting happens to lead with comp/benefits text — it fixes the
   mechanism directly rather than waiting it out. Preferred over (2) because
   it also removes the metro-selection confound: a full-text source isn't
   filtered to whichever jobs happened to disclose salary, so it doesn't
   inherit the disclosure-law-metro skew either.
2. **Disclosed-population growth on the current source** — keep ingesting
   Adzuna commercial postings until at least one skill reaches n≥15 *within
   the disclosed-only, `'ok'`/USD/year population*. At current tag rates
   (~19% of disclosed jobs tagged, top skill ~3 jobs), this needs disclosed
   volume roughly 5-8x today's 178 before the top skill alone clears the bar.
   **Selection caveat**: this unblock only ever describes the *disclosed
   slice* — likely a pay-transparency subpopulation skewed toward
   comp-forward postings and disclosure-law metros (see above) — not the
   commercial market as a whole. Reaching n≥15 makes the number reportable,
   not representative; the resulting premium is "premium among jobs that
   disclose," and that scope must stay in the headline, not a footnote.

Whichever unblocks first, re-run the recon in this doc before rebuilding the
per-skill cut — don't assume the numbers above are still current.
