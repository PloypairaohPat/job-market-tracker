# Dashboards (Metabase)

Six Metabase dashboards, defined as files in the repo and built by one command. Their cards read only the SQL views in `sql/views/` (the same views the written reports use) through a read-only database role, and they repeat the same caveats. Nothing in Metabase is edited by hand: change the files and re-run the provisioner.

Commands below are for Windows PowerShell with `uv`, run from the repo root. Postgres is the compose `db` service, as for the daily task.

> **Never create or edit `.env` with PowerShell `echo` or `>>`.** Windows PowerShell 5.1 writes UTF-16, which puts NUL bytes in the file. Use Notepad or VS Code.

## One-time setup

1. **Set three variables in `.env`** (Notepad: `notepad .env`):

   ```
   METABASE_ADMIN_EMAIL=you@example.com
   METABASE_ADMIN_PASSWORD=<a long password for the Metabase admin user>
   METABASE_READER_PASSWORD=<a different long password for the read-only DB role>
   ```

   Everything else has a default:

   | Variable | Default |
   |---|---|
   | `METABASE_URL` | `http://localhost:3000` |
   | `METABASE_PORT` | `3000` |
   | `METABASE_DB_HOST` | `db` (the compose service name) |
   | `METABASE_DB_PORT` | `5432` |
   | `METABASE_DB_NAME` | taken from `DATABASE_URL` |
   | `METABASE_DB_USER` | `metabase_reader` |

2. **Make sure the views exist and create the read-only role:**

   ```powershell
   uv run alembic upgrade head
   uv run python scripts/apply_views.py          # or: make views
   uv run python -m src.dashboard.reader_role    # or: make bi-grant
   ```

   `metabase_reader` can `SELECT` from every `v_*` view and nothing else. `SELECT * FROM jobs` as that role fails with "permission denied", so a dashboard card can't quietly recompute a metric from base tables. **Re-run it after adding a view** (it only grants views that exist when it runs). It never prints the password.

3. **Start Metabase** (it's in the opt-in `bi` compose profile, so plain `docker compose up -d` and the daily task are unaffected):

   ```powershell
   docker compose --profile bi up -d             # or: make bi-up
   ```

   The first start takes a minute or two. Metabase listens on **http://localhost:3000**, on this machine only.

4. **Build the dashboards:**

   ```powershell
   uv run python -m src.dashboard.provision      # or: make bi-provision
   ```

   - **On a fresh Metabase:** it runs the setup with your admin email and password, connects to Postgres as `metabase_reader`, creates the collection **Job Market Tracker**, and builds every card and dashboard.
   - **Run it again any time:** an unchanged spec makes no changes.
   - **`--dry-run`:** prints what it would change without changing anything.

5. Open **http://localhost:3000** and log in with the admin email and password.

To stop Metabase without touching Postgres or the daily task:

```powershell
docker compose --profile bi stop metabase
```

## The dashboards

Every dashboard opens with a text card naming its sources and the view or report it mirrors, plus a **Data window** card showing the first and last snapshot date and the n behind it. A database whose name contains `demo` or `test` also gets a top banner, **DEMO DATA: synthetic, not market findings**.

| Dashboard | Public? | Shows | Caveats carried |
|---|---|---|---|
| **Ingestion health** | yes | distinct jobs per day by source, new jobs per day, Adzuna calls per day, runs by status, current streak vs 60 days, missing days | A missing day is a gap (the line breaks), never a zero, and it can't be backfilled. Dates are UTC. Days before the run log show 0 runs. Mirrors `python -m src.pipeline.health`. Read this one first: if it's wrong, every other dashboard is too. |
| **Market overview** | yes | jobs by market, jobs by tracked metro, seniority mix, top employers by normalized name | Metro is the tracked-metro **allowlist** (instrument-limited), not all locations. Seniority comes from titles only (instrument-limited); "no title signal" is shown, never folded into mid. Postings with no company are counted separately. |
| **Salary** | yes | disclosed salary distribution, disclosed median by seniority (with n, p25/p75, small-n flag), predicted-vs-disclosed comparison | Headline numbers are **employer-disclosed only**. Adzuna-predicted salaries appear only in the comparison card, split by `salary_is_predicted`, never blended. Commercial, annual USD, `salary_quality = 'ok'` only. |
| **Skills** | yes | skill-tag share by category per market, top commercial skills, top federal skills | Commercial text is truncated at ~500 characters, so a skill's absence there is not evidence it isn't required. It's a composition, not a magnitude. Rates always sit next to n (federal n is small). |
| **Transparency** | yes | salary present vs disclosed, fields that are market facts, instrument-limited fields | `pct_seniority_present`, `pct_metro_present` and federal `pct_remote_true` are labelled **instrument-limited**: they measure our classifiers, not employer disclosure. |
| **Visa outlook** | **no** (your job search) | jobs per bucket, strong and possible jobs with evidence and URL, employer sponsorship history | The full "What this can't tell you" list from `src/visa/README.md`: an LCA isn't an approval or a hire, counts favour large filers, truncated text hides signals, cap-exempt is only a hint, E-Verify isn't covered, and rules change, so check with your DSO. |

Every grouped number shows its n. Groups under 10 carry a `small_n` flag; nothing is hidden.

## Changing a card or dashboard

Everything lives in `dashboards/`:

- `dashboards/<slug>.json` holds one dashboard: name, description, `public`, and its cards with their grid position and size (the grid is 24 columns wide).
- `dashboards/sql/<key>.sql` holds one question's SQL. It may read only `v_*` views.

To change something:

1. Edit the files.
2. Run `uv run pytest tests/test_dashboard_spec.py`. The validator enforces the rules above:
   - `v_*` views only
   - every card described
   - salary never blended
   - the skills truncation caveat
   - instrument-limited labels
   - no overlapping or off-grid cards
   - unique keys
3. Re-run `uv run python -m src.dashboard.provision`.

Cards and dashboards are matched by their **key** (the file name), through the last line of each item's description in Metabase ("Defined in dashboards/..."). Renaming a title updates the item in place. Renaming a key creates a new item and deletes the old one. Deleting a card from the spec deletes it from Metabase, but only items inside the *Job Market Tracker* collection that carry that line. Anything you make by hand in Metabase, or keep in another collection, is never touched. Edits made in Metabase to provisioned items are overwritten on the next run.

If a card needs data no view exposes, add a view to `sql/views/` (in the header-comment style, with n beside every aggregate), then run `make views`, the reader-role command, and provision.

## Rotating the reader password

1. Change `METABASE_READER_PASSWORD` in `.env`.
2. Run `uv run python -m src.dashboard.reader_role`.
3. Run `uv run python -m src.dashboard.provision --reconnect` to send the new password to Metabase.

## Why there are no public links yet

The provisioner can share the public dashboards (all but Visa outlook) with `--public-links`. It is **off by default**, and you shouldn't use it on the laptop:

- Metabase listens on 127.0.0.1 only, so a public link wouldn't work from anywhere else anyway.
- Exposing the laptop to the internet isn't worth the risk.

Public links belong on the always-on server (Milestone D, [docs/deploy.md](deploy.md)), behind HTTPS, with Postgres as Metabase's app database. They're the last step of its cut-over. Visa outlook is `public: false` and never gets a link: the provisioner removes one if it finds it.

## Metabase version

The image is pinned to `metabase/metabase:v0.64.3.4`. The provisioner's API calls are written against that version (MBQL 5 native queries, dashcards saved through `PUT /api/dashboard/{id}`), and the validator's 24-column grid matches it. To upgrade:

1. Change the tag in `docker-compose.yml`.
2. Run `docker compose --profile bi up -d`.
3. Run `uv run python -m src.dashboard.provision --dry-run`, then a real run.
4. Run the end-to-end test against it:

   ```powershell
   $env:METABASE_URL = "http://localhost:3000"
   uv run pytest tests/test_metabase_e2e.py
   ```

   It runs every card through the API.

If the API changed shape, the test says which call failed. Metabase's app database (H2, in the `metabase_app_data` volume) is disposable: everything is rebuilt from `dashboards/`, so deleting the volume and re-provisioning is always safe.

## Trying it on demo data

`uv run python scripts/seed_demo_data.py --full` builds a synthetic dataset where every panel has data:

- four weeks of history with one missing day
- both markets
- every visa bucket, using FAKE employers only

It **truncates** its target first, so it only runs against a local database whose name contains `demo` or `test`. Point `DATABASE_URL` (and `METABASE_DB_NAME`) at such a database, never at `jobmarket`.
