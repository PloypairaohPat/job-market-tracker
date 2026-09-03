# Field completeness / transparency profile — methods note

Phase 3 #3. Companion to `sql/views/v_field_completeness.sql` (source of truth). This
note carries the evidence behind each field's market-fact vs instrument-limited label —
the SQL comments summarize the verdict, this doc shows the work.

## Why per-source, never pooled

Federal (USAJobs) discloses salary on essentially every posting because federal pay
bands are public by law — that isn't a transparency win, it's the ~100% baseline that
makes commercial's disclosure rate legible as a **choice**. Blending the two into one
"% salary populated" number erases the only comparison that matters here. Every field
below is reported per source; no pooled figures appear anywhere in the view or chart.

## Seniority — title-only classifier, sampled diagnosis

`classify_seniority()` (`src/cleaning/seniority.py`) reads **the job title only** — a
deliberate, documented scope, not a bug. That means `jobs.seniority IS NULL` measures
"no seniority marker in the title," not "no seniority signal in the posting." The two
claims are different, and only the first is instrument-honest.

Sampled 15 random commercial `seniority IS NULL` rows and checked full description text
(`description_full` where present, else `description`) for cues the classifier
structurally cannot see:

| id | title | cue found in description body |
|---|---|---|
| 63 | DATA ANALYST | "Retail & E-Commerce (**2-3 Years Experience**)" |
| 29 | Data Analyst | "seeking a Data Analyst with **3-5 years of experience**" |
| 925 | Enterprise Business Intelligence Analyst | "may often **lead** cross functional projects" (verb, not a title cue) |
| 931 | Business Intelligence Analyst & Evaluator | "serves as ... **lead** analytics and evaluation professional" (ambiguous — reads closer to a duty description than a leveling signal) |
| remaining 11/15 | — | no seniority-indicating language found in the visible text |

Read as: **2 of 15** sampled NULLs carry an unambiguous years-of-experience cue that a
title-only classifier cannot access by construction. A further 2/15 have a weaker,
ambiguous "lead"-as-verb match not treated as a real hit. The remaining 11/15 show no
signal anywhere — genuine title-and-body silence.

**This sample is too small to re-estimate the true completeness rate** (n=15 out of 736
commercial NULLs) — it is reported as a raw count (2/15), never scaled to a percentage,
per the same discipline as the metro-multiple caveat in `phase_3_findings.md` #1. Its
job is narrower: it establishes that the NULL population is *mixed* (some employer
silence, some instrument miss), which is enough to block reporting `pct_seniority_present`
as a disclosure rate. It is reported only as "% of titles with an explicit marker."

## Metro — allowlist lookup, not a disclosure signal

`assign_metro()` (`src/cleaning/metro.py`) is a strict lookup against a curated list of
8 metros + DC. It is never a default or fallback — a non-null `metro_area` is always a
real match to a tracked city name; a null `metro_area` means "not on the list," not "no
location given."

The view therefore carries two separate columns:

| | commercial | federal |
|---|---|---|
| `pct_location_present` (any parsed location at all) | 100.0% | 75.7% |
| `pct_metro_present` (matches the 8-city+DC allowlist) | 8.9% | 22.9% |

Given a parsed location, the large majority of commercial jobs simply aren't in a
tracked metro — real, specific, parseable cities seen directly in the seniority sample
above (Miami, Phoenix, Charlotte, San Antonio) are absent from the 8-city list. The
8.9%/22.9% figures describe **our coverage list**, not employer location disclosure.
Reporting them as a "how often is location disclosed" number would be the exact
present-vs-informative confusion rule #3 of the recon brief warned about.

## Remote — classifier reads the wrong field for federal

`apply_remote()` (`src/cleaning/apply_cleaning.py`) calls
`detect_remote(job.title, None, job.description)` for every job regardless of source —
it never passes `description_full`. For commercial this is harmless: `description` is
the only text Adzuna gives us. For federal it is a real gap: `description` holds only
the short `JobSummary` field (avg 376 chars); the source's actual telework policy is
stated in `description_full`'s boilerplate ("Telework: Ad-hoc", "Telework: Not
Available", etc.), which the classifier never sees.

Direct check across the 70 federal in-scope jobs:

- "remote"/"telework" mentioned in the short description the classifier reads: **1**
- "remote"/"telework" mentioned in `description_full`: **13**
- mentioned in `description_full` but **not** in the short description at all: **12**

Example (id 3467, "Data Scientist"): *"Position may be eligible for **situational
telework** in accordance with agency policy..."* — present only in `description_full`,
invisible to the classifier.

Not every one of the 12 would flip to `true` if scanned — some read "Telework: Not
Available," a negative signal. The finding isn't "federal is actually more remote than
measured"; it's that **the classifier cannot currently tell**, because it's reading a
field that structurally doesn't carry the answer for this source. Federal's `pct_remote_true
= 0.0%` is not a measured market rate and must not be charted beside commercial's 4.2%
as if the two were comparable.

## Skills — present vs truncation-floored (pointer, not a re-derivation)

Full mechanism and the ~70x federal truncation-collapse number are established in
`docs/findings_commercial_vs_federal_skills.md` (Phase 3 #2) and
`docs/phase_3_findings.md` #1. Restated here only as it bears on completeness:
Adzuna descriptions sit at/near a hard 500-char cap on 1,479/1,483 (99.7%) commercial
rows, so `pct_skill_present` (42.1% commercial vs 98.6% federal) is depressed on the
commercial side by truncation, not by postings genuinely omitting requirements. An
absent commercial skill tag is disproportionately a **recall failure**, not a **skill-free
posting** — present vs informative, same as salary.

## Salary — the clean case (pointer)

No new work here; restating the two-layer split already established in Phase 3 #1
(`v_commercial_salary_clean.sql`) because it's the frame the rest of this investigation
is measured against: 100% of commercial jobs carry *a* salary figure, 12.1% are
employer-disclosed (`salary_is_predicted=false`) — the other 87.9% is Adzuna's model
estimate occupying the same field. Federal: 100% present, 100% disclosed, 0% predicted
(federal pay bands are never modeled).
