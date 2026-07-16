# Cleaning layer (Phase 2)

Everything here derives from stored raw values and is recomputable — the
raw-then-normalized pattern applied to cleaning. Two entry points:

- `python -m src.cleaning.extract_skills` — sync the skill taxonomy and
  extract job↔skill links from descriptions (`--rebuild` after taxonomy
  shape changes)
- `python -m src.cleaning.apply_cleaning` — seniority, salary quality,
  remote upgrade, metro assignment, company normalization (`--only STEP`
  to run a subset)

Design rules enforced throughout:
1. **Flag, don't guess** — no signal means NULL, never a default bucket.
2. **Precision over recall** — every ambiguous pattern has a
   false-positive trap test; add the trap before adding the rule.
3. **Layer, don't destroy** — raw names/values are never modified;
   fuzzy company merges go to CSV for manual review, and approved pairs
   are promoted into `data/company_aliases.json`.
