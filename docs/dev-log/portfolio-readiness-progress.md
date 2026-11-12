# Portfolio readiness: progress

Working file for the portfolio-readiness brief (Parts A to G). Folded
into `docs/dev-log/portfolio-readiness.md` when Parts A to F are done.

- Branch: `claude/portfolio-readiness`, from main at 2f80d85.
- Baseline (clean main, TEST_DATABASE_URL set): **705 passed, 1 skipped**.
- STOP conditions checked on the first run: 2f80d85 is in main; baseline
  green; one alembic head (a02471448340); no `docs/reports/`, no
  `--publish`, no `src/shortlist*`, no remote `claude/portfolio-readiness`.

## Parts

| Part | Status | Commits |
|---|---|---|
| A1 one engine per URL | done | A1 |
| A2 skills step converges | done | A2 |

## Latest test count

716 passed, 1 skipped (after A2).

## Parked questions

| Q | Part | Question | Default built |
|---|---|---|---|
| Q1 | A2 | Should `sync_taxonomy` delete `skills` rows that left the taxonomy? | No: keep the row, log how many are orphaned |
