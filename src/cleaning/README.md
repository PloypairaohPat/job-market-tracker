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

## Promoting approved company pairs

`apply_cleaning --only companies` writes `data/company_merge_candidates.csv`
(`name_a, name_b, relation, similarity, approved`). Mark `approved` (`y`,
`yes`, `x`, `1` or `true`) on pairs that are really the same employer, then
let the helper write the alias file instead of editing the JSON by hand:

```bash
python -m src.cleaning.aliases apply --from data/company_merge_candidates.csv          # dry run
python -m src.cleaning.aliases apply --from data/company_merge_candidates.csv --write
```

The dry run prints the aliases it would add, every refused row with its
reason (a key that isn't normalized, a self-map, a key already mapped
elsewhere, a chain or a cycle), and the diff of the JSON. By default the
longer key is mapped onto the shorter one; add a `keep_a` or `keep_b` column
and mark it to choose the key that survives. `--write` keeps `_meta`, the
`_comment_*` notes and the existing order, and prints the commands to run
next (`apply_cleaning --only companies`, `lca_loader --rekey`, `make views`).
Running it twice adds nothing.

Fallback, by hand: add `"<key>": "<surviving key>"` under `aliases` in
`data/company_aliases.json` (lowercase normalized keys; never point an alias
at another alias), then run the same commands.
