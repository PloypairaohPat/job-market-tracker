# Commercial vs federal skill demand — methods note

Phase 3 #2. Companion to `sql/views/v_skill_category_composition.sql` (primary) and
`sql/views/v_skill_top_by_source.sql` (drill-down). This note carries the two caveats
that don't fit in SQL comments: taxonomy provenance and the symmetric-truncation caveat.

## Taxonomy provenance — the "fitted to federal" seam

The taxonomy grew from 66 to 70 skills *during this investigation*, specifically because
a spot-check of federal descriptions found vocabulary the extractor was blind to:

| Addition | Type | Reason |
|---|---|---|
| SQL ← "structured query language" alias | alias on existing skill | federal descriptions spell it out; commercial postings say "SQL" |
| SPSS | new skill | absent from taxonomy entirely; appeared in federal samples |
| GIS (ArcGIS-anchored) | new skill | absent from taxonomy entirely; appeared in federal samples |
| SSIS | new skill | absent from taxonomy entirely; anticipated federal/enterprise tool |
| SSRS | new skill | absent from taxonomy entirely; appeared in federal samples |

All five were trap-tested in `tests/test_skill_extractor.py` *before* the pattern was
added (precision-first, per the taxonomy's own curation principle), and none were
added or tuned in response to commercial text. **The reader should still know this seam
exists**: the federal side of every composition and drill-down number below reflects a
taxonomy that was partly built by reading federal postings. A skill neither side
mentions, or that federal-specific tooling still lacks a pattern for, remains invisible
to this analysis. The other 65 skills (including everything driving the commercial-side
composition) predate this investigation and were not federal-motivated.

## Symmetric-truncation caveat — this cuts both ways

The prior recon (Phase 3 #2 recon doc, chat record) demonstrated federal's ~500-char
truncated re-extraction collapsed to 0.036 tags/job from 3.371 full-text — a ~70x drop —
because federal's first 500 characters are `JobSummary` mission prose, not a
requirements list. That number is kept **only as a placement-difference demonstration**,
not folded into any rate here (the truncation-matched commercial-500-vs-federal-500 cut
was evaluated and dropped: equal character count isn't equal content, so it doesn't
control for anything).

The caveat that matters for the composition numbers actually shipped: **commercial's
native ~500-char basis is not a neutral baseline either.** Adzuna's front-of-posting
text is exactly where a listing is most likely to sell the role and mention process
(workflow tools, BI dashboards used day-to-day) before it gets to a full stack of
requirements — the same structural mechanism that suppressed federal's early skill
recall could just as easily be **inflating commercial's workflow/bi_tool share** and
**suppressing its language/ml_stats share** (deeper technical requirements lists often
run later in a posting). Federal's disadvantage is well-evidenced (the 70x). Commercial's
possible advantage from the same mechanism is plausible but **not separately measured
here** — no truncation-matched commercial comparison was built, by design. Read the
composition contrast as directionally real (workflow/bi_tool skew commercial,
ml_stats/language skew federal) but treat the exact margins as a floor on the true
contrast, not the contrast itself, until a full-text commercial source can test it.

## Statistics-tag circularity — resolved, not circular

Pre-build check: does the federal `ml_stats`-heavy composition just reflect that we
picked jobs off statistics-labeled occupational series (1530/1560)? Tested by
splitting federal in-scope jobs into three independently-derived buckets and checking
the "Statistics" skill tag rate *within* each:

| Bucket | n | Statistics-tagged | rate |
|---|---|---|---|
| Series 1530/1560 (Statistics / Data Science label) | 29 | 27 | 93.1% |
| Series 1515 (Operations Research — not a statistics label) | 27 | 25 | 92.6% |
| Skill-density-admitted (Management And Program Analysis) | 14 | 1 | 7.1% |

The rate holds essentially unchanged in the Operations Research series — a bucket
admitted by occupational-series code, not by any statistics-related label — so this is
not circular (labeling a job "Statistics" and then finding a Statistics tag). It reads
as a genuine market statement for the 56/70 (80%) of federal in-scope jobs identified
via clean series codes. The skill-density-admitted slice (14/70, 20%) does **not** share
this pattern — worth knowing, since it means the federal ml_stats skew is concentrated
in, not uniform across, the in-scope population.
