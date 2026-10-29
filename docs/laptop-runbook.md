# Laptop runbook

The routine for the Windows laptop, in **Windows PowerShell** with `uv`, from the repo root (for example `C:\path\to\repo`). Quote every path: the repo path may contain spaces.

> **Run one command at a time.** When you paste several lines at once, PowerShell runs every line even if an earlier one failed. After a command, `$LASTEXITCODE` is `0` if it worked. The only multi-line blocks below are loops that check `$LASTEXITCODE` and stop at the first failure.

`uv run python -m src.doctor` checks the whole setup in one go. It changes nothing, and for every problem it prints the exact command that fixes it. When something looks wrong, start there.

## After every `git pull`

```powershell
uv sync
uv run alembic upgrade head
uv run python scripts/apply_views.py
uv run python -m src.doctor
```

- `uv sync` installs any new dependency.
- `alembic upgrade head` applies any new migration (doctor check 3).
- `apply_views.py` creates or updates every SQL view (doctor check 4).
- The doctor should end with `exit code 0`. A **FAIL** line needs fixing: run the command on its `fix:` line. A **WARN** is worth reading but doesn't block anything. **SKIP** means the check doesn't apply (the scheduled-task check off Windows, or a database check while the database is down).

If you use the Metabase dashboards, also run:

```powershell
uv run python -m src.dashboard.reader_role
uv run python -m src.dashboard.provision
```

The first grants the read-only role access to any new view; the second rebuilds the dashboards ([docs/dashboard.md](dashboard.md)).

## Weekly

```powershell
uv run python -m src.doctor
uv run python -m src.pipeline.health
```

Look at the health check's **H7** line (days without a snapshot) and the streak ([docs/daily-operation.md](daily-operation.md), "How to tell the clock is running").

Then re-render the reports. This loop stops at the first one that fails:

```powershell
foreach ($r in @("commercial-vs-federal-skills", "how-much-employers-disclose", "employers-and-sponsorship", "what-postings-pay")) {
  uv run python -m src.reports $r
  if ($LASTEXITCODE -ne 0) { Write-Host "STOP: $r"; break }
}
```

Each lands in `reports\<slug>\report.md` ([docs/reports.md](reports.md)). `reports\` is gitignored: rendered output is never committed.

## Reviewing company and employer matches

Two CSVs propose near-duplicate names for you to review: `data\company_merge_candidates.csv` (from `apply_cleaning --only companies`) and `data\sponsor_match_candidates.csv` (from `uv run python -m src.visa.sponsor_match`). Open one in Excel, type `y` in the `approved` column of each pair that is really the same employer, and save it as CSV. Then, one command at a time:

```powershell
uv run python -m src.cleaning.aliases apply --from "data\sponsor_match_candidates.csv"
uv run python -m src.cleaning.aliases apply --from "data\sponsor_match_candidates.csv" --write
uv run python -m src.cleaning.apply_cleaning --only companies
uv run python -m src.visa.lca_loader --rekey
uv run python scripts/apply_views.py
uv run python -m src.reports employers-and-sponsorship
```

The first command is a dry run: read the aliases it would add and the rows it refuses (with the reason) before running the second. To choose which name survives, add a `keep_company` or `keep_lca` column (`keep_a` / `keep_b` in the company CSV) and type `y` in it. `company_aliases.json` is tracked in git: commit the change once the re-render looks right. Do the same with `data\company_merge_candidates.csv`.

## Where files go

| What | Where | Committed? |
|---|---|---|
| LCA disclosure files (.xlsx) | `data\lca\` | never (`data\` is gitignored) |
| Match-review CSVs, exports | `data\` | never |
| Daily logs | `logs\daily-YYYY-MM-DD.log` | never |
| Rendered reports | `reports\<slug>\` | never |
| Credentials | `.env` | never |

Anything with real data that sits anywhere else could be committed by mistake. Doctor check 8 finds untracked `.xlsx`, `.csv`, `.dump` and `.log` files outside `data\` and `logs\`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `connection refused` on `localhost:5432` (or "could not connect to server") | The Postgres container isn't running. Docker Desktop hasn't started yet, or the container predates the `restart: unless-stopped` policy | Open Docker Desktop and wait for **Engine running**, then `docker compose up -d db`. Doctor check 2. To keep it from happening again: [docs/daily-operation.md](daily-operation.md), "After a reboot or wake" |
| `` warning: `VIRTUAL_ENV=...\.virtualenvs\.venv` does not match the project environment path `.venv` `` | Another virtualenv is active in this terminal (VS Code activates one) | Harmless: uv uses `.venv` anyway. To silence it, run `deactivate`, or untick VS Code's `python.terminal.activateEnvironment` setting. Doctor check 9 |
| `STOP: LCA_Disclosure_Data_...xlsx` from the LCA loading loop | The loader refused that file (for example, too many decisions outside its `--fiscal-year`, or a required column missing), and the loop stopped | Read the loader's message just above `STOP:`: it says why. Fix it and re-run the loop from that file. Files loaded before it are fine, and reloading one is safe (rows are upserted on `case_number`) |
| dol.gov answers `403 Forbidden` to a script or `Invoke-WebRequest` | DOL's site blocks automated downloads | Download the files in your browser and save them into `data\lca\` |
| An `.xlsx` (or `.csv`) in the repo root | Saved to the wrong folder. Git sees it as an untracked file and could commit it | `Move-Item "LCA_Disclosure_Data_FY2026_Q3.xlsx" "data\lca\"`. Doctor check 8 prints the command for each file |
| NUL bytes in `.env` (Python can't read it) or in README.md (a diff shows every character spaced out) | `echo ... >> file` in Windows PowerShell 5.1 writes UTF-16 | Re-save the file as UTF-8 in Notepad (**File → Save As → Encoding: UTF-8**). For a tracked file like README.md, `git checkout -- README.md` restores it. Never use `echo` or `>>` on these files. Doctor check 1 catches it in `.env` |
| A pasted multi-line block where one command failed and the rest ran anyway | PowerShell runs every pasted line, whatever happened to the one before | Run one command at a time, and check `$LASTEXITCODE` (0 = worked) before the next. The loops in these docs check it and stop |
| A database dump that won't restore | `pg_dump ... > file.dump` in PowerShell re-encodes the binary output and corrupts it | Use `.\scripts\windows\export_db.ps1`: it writes the dump inside the container and copies it out ([docs/deploy.md](deploy.md)). Never redirect a dump with `>` |
