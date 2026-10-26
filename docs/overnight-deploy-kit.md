# Overnight run: a deploy kit for a small VPS, plus README polish (Milestone D)

## Report

- **Branch:** `claude/deploy-kit`, off `main` at `643a734` ("Merge pull request #3 from PloypairaohPat/claude/metabase-dashboards"). This session's setup named a different working branch; per the brief, everything went to `claude/deploy-kit`.
- **Commits on top of main `643a734`:** 10, plus this report (listed below). **Pushed:** yes, after every green commit. No force push, nothing to `main`, no PR.
- **STOP conditions:** none held.
  - `643a734` is in main's history.
  - The baseline was green (447 passed, 1 skipped).
  - `alembic heads` showed one head (`a02471448340`).
  - main had no `deploy/` and no `Dockerfile`.
- **Verification setup:**
  - Local Postgres 16 on 127.0.0.1, with a freshly recreated `jobmarket_test` before every commit.
  - A gate script that **exits on the first failure**: pytest, ruff check, ruff format, the alembic round trip, `make views` twice, and shellcheck on every added or changed shell script.
  - Versions: Python 3.13.17, SQLAlchemy 2.1.6, alembic 1.20.1, psycopg2-binary 2.9.13, pytest 9.1.1, ruff 0.17.2, shellcheck 0.11.0 (from `shellcheck-py`, not added to pyproject), Docker 29.9.2, Compose 5.6.1.
- **Compare:** https://github.com/PloypairaohPat/job-market-tracker/compare/main...claude/deploy-kit?expand=1
- **Afterwards:** the VM's prod stack was taken down with its volumes (`down -v`), and the throwaway root `.env` was deleted. Neither was ever committed.

| Check | Baseline (clean main) | Final |
|---|---|---|
| `pytest` with `TEST_DATABASE_URL` | 447 passed, 0 failed, 1 skipped | **459 passed, 0 failed, 1 skipped** (+10 ping cases, +2 provisioner tests). The skip is the Metabase e2e test, which needs `METABASE_URL`. It was run separately against the prod stack and passed (below) |
| `ruff check .` (0.17.2) | clean | clean |
| `ruff format --check .` (0.17.2) | clean | clean, 107 files. ruff 0.17 counts Markdown files too, so the new `docs/deploy.md` and this report each raised the count by one |
| alembic upgrade → downgrade → upgrade on a freshly recreated database | clean | clean (no migration in this milestone) |
| `make views` on a fresh database, twice | 9 views | 9 views, twice |
| Image build (`docker build`, `python:3.12.15-slim-trixie`) | — | **builds** (982 MB); `scripts/verify_image.sh` OK (details below) |
| CI `image` job (build + verify, no push, no login) | — | **green** on every push |
| shellcheck 0.11.0 on every added/changed script | — | **clean**: `deploy/backup.sh`, `bootstrap.sh`, `ensure_metabase_db.sh`, `import_db.sh`, `initdb/10-metabase-app.sh`, `restore.sh`, `scripts/verify_image.sh` |
| `systemd-analyze verify` (systemd 255) | — | **verified**: its only complaint is that `/home/deploy/job-market-tracker/deploy/backup.sh` doesn't exist here (it's a server path); with that one ExecStart swapped for `/usr/bin/true` it's clean |
| PowerShell parse check | — | **run**: PowerShell 7.4.6, one attempt, from the official GitHub release tarball. 0 parse errors and ASCII only in `export_db.ps1`, `register_daily_task.ps1` and `run_daily.ps1`. `export_db.ps1` was also **executed** under pwsh on Linux (below). Windows PowerShell 5.1 itself wasn't available |
| GitHub Actions CI on the branch | — | runs **#18–#27 all green** (test 3.11, test 3.12, image). The Node 20 deprecation warning is gone since #18 (checkout v6, setup-python v6) |

### The image

`scripts/verify_image.sh job-market-tracker:local` on the final build:

- `/app` contains only `README.md alembic.ini dashboards migrations pyproject.toml scripts sql src`
- no `.env*`, `*.dump`, `data/`, `logs/`, `tests/`, `notebooks/` or `.git` anywhere in the image
- runs as uid 10001
- pytest and ruff aren't installed
- the working directory `/var/lib/jobmarket` (where the runner writes `logs/` and `data/`) is writable
- `alembic -c /app/alembic.ini heads` → `a02471448340 (head)`
- the default command (`health --help`) runs

Alembic, views and health running from the image against a database: verified in the stack below.

### Step 3: the prod stack in this VM

**Setup:**

- The stack (`db`, `metabase`, `caddy`) ran from `deploy/docker-compose.prod.yml` with a throwaway root `.env`: fake passwords, `SITE_ADDRESS=:80`, `JOBMARKET_DB=jobmarket_demo`. Ports 80 and 443 were free on the VM, so Caddy used them.
- Demo data: `seed_demo_data.py --full` into `jobmarket_demo` on the VM's own Postgres (the seed's guard untouched), then `pg_dump -Fc`, then restored into the stack's `db` as `jobmarket_demo`.

**Final run:** all checks were re-run at the end, on an image rebuilt from the final commit. An earlier pass had used a stale image; see Surprises.

| Check | Result |
|---|---|
| Demo data in the stack | jobs 634, job_snapshots 6791, ingestion_runs 54, lca_cases 26 |
| `alembic upgrade head` and views through `docker compose run --rm pipeline` | head `a02471448340`; 9 views applied |
| Reader role (`python -m src.dashboard.reader_role` in the pipeline container) | `metabase_reader` can read 9 views |
| Provisioner with `--public-links`, twice | step 3: from the host against 127.0.0.1:3000 (standing in for the SSH tunnel). Final: in the pipeline container. Both final runs: **created 0, updated 0, deleted 0, unchanged 36**; 5 public links, printed with `MB_SITE_URL` |
| Playwright **through Caddy**, every public link | **5/5 render**: Ingestion health 10 dashcards, Market overview 7, Salary 6, Skills 6, Transparency 6. Nothing still loading, no error text, no login page, demo banner present. The only failed request is `/api/session/properties` (404, blocked on purpose, Q11). Screenshots stayed in the scratchpad |
| Visa outlook has no public link | admin API: `public_uuid` is null for Visa outlook; exactly 5 dashboards are public |
| Blocked paths through Caddy | **404 with an empty body** for `/`, `/auth/login`, `/api/session`, `/api/user/current`, `/api/card`, `/api/dashboard`, `/api/setup`, `/api/session/properties`, `/api/health`, `/api/database`, `/api/collection`, `/admin`, `/question/1`, `/dashboard/1`, and `POST /api/session` |
| `/auth/login` shows no Metabase login | 404, 0 bytes |
| Public links' own API calls through Caddy | each public page 200; `GET /api/public/dashboard/<uuid>` 200; **all 24 public card queries completed** with rows (7 + 5 + 4 + 4 + 4) |
| `db` publishes no port | `docker ps` shows `5432/tcp` (exposed, not published); `docker compose port db 5432` → `:0` |
| Nothing else listens on host port 5432 | the only listener is `127.0.0.1:5432`, the VM's own Postgres (read from `/proc/net/tcp`) |
| Metabase's app data in Postgres, not H2 | `MB_DB_TYPE=postgres`, `MB_DB_DBNAME=metabase_app`; `metabase_app` has 174 tables owned by role `metabase_app`; **0 H2 files** in the container |
| `pipeline python -m src.pipeline.daily --skip adzuna usajobs` | exit 0: adzuna and usajobs skipped, cleaning ok, skills ok (70 skills, 634 jobs), health pass |
| `pipeline python -m src.pipeline.health` | overall PASS, exit 0 |
| `tests/test_metabase_e2e.py` against the stack's Metabase | **1 passed**: provisioned twice with the same ids, then every card ran |
| Container logs | db, metabase and caddy use the `local` (rotating) log driver; `docker compose logs` still works |
| Memory at rest (demo data) | metabase 1.375 GiB, db 143 MiB, caddy 12 MiB |

### Backups (step 5)

Round trip on the demo stack, re-run on the final code:

1. `deploy/backup.sh` wrote `jobmarket_demo_<UTC>.dump` (300K) and `metabase_app_<UTC>.dump` (1.2M), both mode 600.
2. `restore.sh` into the non-empty `jobmarket_demo` without `--force` is **refused**, exit 1: "refusing: database jobmarket_demo is not empty (11 tables)".
3. Then: drop the database, restore it.

Counts before and after are identical: **jobs 634, job_snapshots 6791, ingestion_runs 54, lca_cases 26**.

Also verified in step 5:

- **Retention:** 15 seeded dumps per database became 14, and unrelated files in the directory were untouched.
- **`metabase_app` restore** (Metabase stopped, `--force`, then started, as `docs/deploy.md` says): 174 tables, Metabase healthy, the same public link answers 200, and provisioning changes nothing.

### Moving the laptop's data (step 6)

| Path | Export counts | Import counts |
|---|---|---|
| Emulated on Linux: `pg_dump -Fc -f` on the VM's Postgres (`jobmarket_demo`), copied out, then `deploy/import_db.sh` | jobs 634, job_snapshots 6791, ingestion_runs 54, latest snapshot_date 2026-10-26 | **identical** |
| `export_db.ps1` **executed** under pwsh 7.4.6 against a throwaway laptop-stack `db` container, then `deploy/import_db.sh --force` with the final image | same four lines | **identical** |

Details:

- **The pwsh run used the real `docker-compose.yml`.** A scratchpad override (via `COMPOSE_FILE`) gave the container a `*_demo` database, its own volume and port 15432, so it wouldn't clash with the VM's Postgres. `docker-compose.yml` itself is unchanged.
- **The `.ps1` cleaned up after itself:** its temp file was gone from the container afterwards. The printed SHA256 matched `sha256sum` of the copied file.
- **`import_db.sh` without `--force`** refused the non-empty database (11 tables). With `--force` it:
  - restored the dump
  - ran migrations, the 9 views and the reader role
  - provisioned with "unchanged 36"
  - printed the same four lines

  Afterwards all five public dashboards still rendered through Caddy.

### Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Image builds; no .env, data/, logs/, tests/; CI build job and bumped actions | **met** |
| 2 | Public dashboards render through Caddy with no card errors; blocked paths 404; Visa outlook has no public link; db publishes no port; Metabase app data in Postgres `metabase_app` | **met** |
| 3 | Backup/drop/restore counts match; restore.sh refuses a non-empty database without `--force` | **met** |
| 4 | Export/import counts match (export emulated; .ps1 parse-checked) | **met**: emulated *and* run under pwsh 7.4.6; 0 parse errors |
| 5 | Ping only when configured, never changes the exit code, masked in logs (tested) | **met**: `tests/test_daily_ping.py`, 10 cases with a fake HTTP session |
| 6 | shellcheck clean; systemd units verified or reported | **met** |
| 7 | Suite green (447 → 459, 1 skip), ruff clean, migration round trip clean, `make views` twice | **met** |
| 8 | Nothing real committed | **met** (below) |
| 9 | No live job/government API called; no remote host except Docker Hub and GitHub | **met for the APIs**. PyPI was also contacted by `pip install .` inside the image build (below) |

**8. Nothing real committed:**

- `git diff main --stat` lists 33 files: code, tests, docs, `deploy/`, `Dockerfile`, `.dockerignore`, `.gitignore`, CI. There are no data, log, dump, screenshot or `.env` files. `deploy/.env.example` holds placeholders only.
- The brief's `git grep` for Gmail addresses and Windows user-profile paths matches nothing, on the branch or on main.
- In the added lines:
  - the only email is `you@example.com`
  - the only IPs are `203.0.113.10` and `127.0.0.1`
  - the domains are `example.com` placeholders (`jobs.example.com`, `hc.example.com` in tests), plus public service names the work needs or the brief names:
    - `download.docker.com` (Docker's apt repository, in `bootstrap.sh`)
    - `github.com` and `raw.githubusercontent.com` (this public repo's URL)
    - `healthchecks.io` and `hetzner.com` (named by the brief)
    - `containerd.io` (a Debian package name)

**9. How I know no live job or government API was called:**

- Every pipeline run in the stack used `--skip adzuna usajobs` (each summary shows both "skipped"), and the throwaway `.env` had empty `ADZUNA_*` and `USAJOBS_*` values. The `ingestion_runs` count stayed at the seeded 54.
- The test suite uses fixture-backed clients and fake sessions.
- I scanned all 360 Bash commands in this session's transcript:
  - none names an Adzuna, USAJobs or DOL host
  - there's no `ssh` or `scp`
  - the only URLs fetched with curl or git were GitHub's (below) and local addresses
- Remote hosts contacted:
  - **Docker Hub** (`registry-1.docker.io`, which returned 429s) and its public pull-through mirror **mirror.gcr.io**, for the postgres, caddy, python, metabase and mermaid-cli images. The brief allows a mirror; the digests were checked against the tags.
  - **GitHub:** git push, the GitHub MCP API (CI status), the PowerShell 7.4.6 release, and Caddy's docs from `raw.githubusercontent.com` (the brief points there for the IP-certificate question).
  - **PyPI**, from `pip install .` inside `docker build`. The brief's own image step needs it.
- Not ruled out: the Metabase container's own background version check, which goes to Metabase's update server, not a job or government API.

## What shipped

| # | Commit | What |
|---|---|---|
| 1 | `162693b` | CI: `actions/checkout@v6`, `actions/setup-python@v6` (Node 24); nothing else in CI changed |
| 2 | `5016b06` | Pipeline image: Dockerfile, .dockerignore, `scripts/verify_image.sh`, CI `image` job |
| 3 | `15f14d3` | Production stack in `deploy/`: compose, initdb for `metabase_app`, `ensure_metabase_db.sh`, Caddyfile, `.env.example`; `prod-*` Make targets; provisioner prints public links with `MB_SITE_URL` |
| 4 | `21db016` | Fixes from the step-3 end-to-end check |
| 5 | `5b685c6` | systemd units (daily 11:15 UTC, backup 03:30 UTC, both `Persistent=true`) and the optional dead-man's-switch ping |
| 6 | `74ab16c` | `deploy/backup.sh` and `deploy/restore.sh` |
| 7 | `9ba467d` | `scripts/windows/export_db.ps1`, `deploy/import_db.sh`, `deploy/row_counts.sql`; `*.dump` gitignored; restore.sh accepts relative paths |
| 8 | `61397c9` | Fix: rotate the prod stack's container logs |
| 9 | `0501ca8` | `deploy/bootstrap.sh` and the runbook `docs/deploy.md`; the cron advice in daily-operation.md now points to the runbook |
| 10 | `20bd3dc` | README: "In three minutes", Mermaid diagram, "How it runs", "Findings so far", status, roadmap |
| 11 | (this) | This report |

**1. CI.** Both actions moved to their Node 24 majors.

- I couldn't read the actions' release pages: this session's GitHub access is scoped to this repo, and I didn't work around that.
- I picked v6 for both from what I knew, then confirmed it on CI: run #18 green, and the Node 20 warning gone.

**2. Pipeline image.**

- **Base:** `python:3.12.15-slim-trixie`, an exact tag.
- **User:** non-root, uid 10001.
- **Install:** `pip install .` (no dev extras). Code lives in `/app` on `PYTHONPATH`. The working directory is `/var/lib/jobmarket`, a volume in the stack, so the runner's relative `logs/` and `data/` never land in the image.
- **Default command:** a harmless one (`python -m src.pipeline.health --help`).
- **.dockerignore** excludes `.env*`, `data/`, `logs/`, `*.dump`, `.venv/`, `.git/`, `notebooks/`, `tests/`, `docs/`, `deploy/` and caches.
- **CA secret:** an optional BuildKit secret `extra_ca` lets pip trust a TLS-intercepting proxy's CA (needed in this sandbox) without storing it in the image. Builds elsewhere ignore it.

**3. Production stack** (`deploy/docker-compose.prod.yml`, project `jobmarket`):

- **`db`:** `postgres:16`. `POSTGRES_PASSWORD` is required (compose fails with "required variable POSTGRES_PASSWORD is missing a value"). **No ports**, a named volume, a health check.
- **`metabase`:** `v0.64.3.4`, the laptop's pin.
  - Its app database is Postgres `metabase_app`, owned by role `metabase_app`.
  - `MB_SITE_URL` comes from `.env`, and tracking is off.
  - Java heap: `-Xmx${METABASE_JAVA_HEAP:-1536m}` (Q3).
  - Port `127.0.0.1:3000` only.
- **`caddy`:** `caddy:2.11.7-alpine` on 80 and 443, with `deploy/Caddyfile` and data/config volumes.
- **`pipeline`:** the image in a `job` profile, run only with `docker compose run --rm`. It reads `env_file: ../.env`, and its `DATABASE_URL` points at host `db`. An optional `JOBMARKET_DB` (default `jobmarket`) let this VM test with a `*_demo` database.
- **Initdb:** `deploy/initdb/10-metabase-app.sh` creates the role and database on a fresh volume (and re-sets the password). `deploy/ensure_metabase_db.sh` runs the same script on an existing volume.
- **Caddyfile:**
  - the site address is `{$SITE_ADDRESS}`
  - only `/public/dashboard/*`, `/api/public/*`, `/app/*` and `/favicon.ico` reach Metabase, and everything else gets **404**
  - HSTS, nosniff, Referrer-Policy and Permissions-Policy headers; `Server` removed
  - JSON access log to stdout
- **Make targets:** `prod-build`, `prod-up`, `prod-down`, `prod-ps`, `prod-logs`, `prod-metabase-db`, `prod-migrate`, `prod-views`, `prod-grant`, `prod-provision ARGS=...`, `prod-daily ARGS=...`, `prod-health`.

**4. Fixes from step 3:**

- **The provisioner's `--public-links` wasn't idempotent.** v0.64 answers `GET /api/setting/enable-public-sharing` with an empty 204, so every run re-sent the setting. It now reads `/api/session/properties` once per run. The fake Metabase behaves like v0.64, and a regression test fails without the fix.
- **`JOBMARKET_DB` added.**
- **Caddyfile note:** the public page's `/api/session/properties` request stays blocked on purpose.
- **`.env.example`:** Metabase rejects common passwords, so it says to use `openssl rand -hex 24`.

**5. Scheduling and ping.**

- **`jobmarket-daily.service`/`.timer`:** `docker compose ... run --rm pipeline python -m src.pipeline.daily` at **11:15 UTC** (07:15 EDT, 06:15 EST), `Persistent=true`, and `TimeoutStartSec=1h`.
- **`jobmarket-backup.service`/`.timer`:** at **03:30 UTC**, hours away from the daily run.
- **The ping:** when `HEALTHCHECK_PING_URL` is set, the daily runner GETs the URL after a successful run, or `<URL>/fail` after a failed one, with a 10 s timeout.
  - A failed ping is logged and never changes the exit code.
  - Nothing is sent on a dry run, when another run holds the lock, or when the variable is empty.
  - The URL is a secret: masked in logs together with its path, because `requests` errors print host and path separately.
  - It's tested with a fake session.

**6. Backups.**

- **`backup.sh`:**
  - dumps both databases with `pg_dump -Fc` *inside* the container, then copies each out with `compose cp`, never through a redirect
  - names files with UTC stamps and keeps the newest 14 of each
  - deletes only files matching its own pattern
  - logs sizes
  - files are mode 600 (`compose cp` would otherwise leave 666)
- **`restore.sh <dump> <db> [--force]`:**
  - restores into a fresh database and refuses a non-empty one without `--force`
  - restores `metabase_app` owned by its role
  - doesn't restore privileges; re-run `make prod-grant`, which `import_db.sh` does for you

**7. Moving the data.**

- **`export_db.ps1`** (ASCII only, no `>`):
  - checks that the db container is running
  - runs `pg_dump -Fc -f` inside it, then `docker compose cp` to `$HOME\jobmarket-export` (outside the repo)
  - prints the size, the SHA256 and the four counts, then the scp and import commands
- **`import_db.sh`** runs, in order:
  1. `restore.sh`
  2. starts db and metabase
  3. migrations
  4. views
  5. the reader role
  6. provisioning (no public links)
  7. the same four counts
- **`deploy/row_counts.sql`** is shared by both, so the outputs compare line by line.

**8. Log rotation (fix).** Caddy logs every request to stdout, and Docker's default `json-file` driver never rotates, so a small server's disk would slowly fill up. db, metabase and caddy now use the `local` driver: 5 × 20 MB per container.

**9. Bootstrap and runbook.**

- **`bootstrap.sh`** (Ubuntu 24.04, run once as root; untested on a real server):
  - checks the SSH key argument (a single public-key line, never stored in the repo)
  - installs Docker Engine from Docker's apt repository, plus git, make, ufw and unattended-upgrades
  - creates user `deploy` with the key, in the docker group, with sudo (Q9)
  - SSH: key-only login, via a `10-` drop-in so it wins over `50-cloud-init.conf`; root keeps key-only login (Q10)
  - ufw: allow 22, 80 and 443 in, deny the rest
  - turns on unattended-upgrades
  - clones the repo and creates `.env` from `deploy/.env.example` (mode 600; it says to use nano)
  - creates `/var/backups/jobmarket` (owned by deploy, mode 700)
  - installs the units and enables **only the backup timer**

  It's idempotent where practical and shellcheck clean. Four invalid inputs were tested here and refused before any change; a valid run would have reconfigured this VM, so it wasn't run.
- **`docs/deploy.md`** walks a beginner from Windows through:
  - spec, not price
  - `ssh-keygen -t ed25519`, the provider console, first login
  - the three HTTPS address options (Q1)
  - bootstrap and `.env`: job-source keys stay empty until the cut-over, so nothing on the server can spend Adzuna calls early
  - starting the stack
  - the SSH tunnel for Metabase admin
  - an optional rehearsal, then the five-step cut-over
  - rollback to the laptop, with the server's data
  - backups and restore (including `metabase_app`, which keeps public link addresses)
  - updating, the dead-man's switch, and a "what can go wrong" table
- **`daily-operation.md`** used to suggest a cron job for the server; next to the systemd timer that would double the daily run, so it now points to the runbook.

**10. README.**

- **"In three minutes"**, from PROJECT_GUIDE's elevator pitch, tightened (Q8). It drops what the repo doesn't show:
  - "thousands of postings"
  - skill salary premiums (deferred)
  - spaCy (the extractor is a curated taxonomy)
  - Prefect
  - "runs on a Hetzner VPS"
- **A Mermaid diagram** replaces the Adzuna-only ASCII one: sources → `raw_responses` → cleaning, skills and visa → SQL views → dashboards and findings, with the daily runner, run log, budget guard and health check. It was rendered with mermaid-cli 12.2 here to check the syntax.
- **"How it runs":** laptop vs server, linking the three guides.
- **"Findings so far":** links only, plus a placeholder for the public link.
- **Updated:** the status line, tech stack, project structure and roadmap. The quick start is unchanged; it was re-run here on a fresh demo database (migrate, seed, health).

## Parked questions

| Q | Question | Recommendation (built) |
|---|---|---|
| 1 | HTTPS address: own (sub)domain, bare IP, or HTTP only | (a) a subdomain you control |
| 2 | Server size and CPU: x86 4 GB vs ARM | (a) x86, 4 GB |
| 3 | Metabase Java heap on 4 GB | (a) 1536m |
| 4 | Dead-man's-switch service and who gets alerts | (a) healthchecks.io free tier, your email |
| 5 | Off-server backup copies; retention count | (a) occasional scp to the laptop; keep 14 |
| 6 | fail2ban on top of key-only SSH and ufw | (b) not now |
| 7 | A read-only copy on the laptop | (b) on-demand restore of a server backup |
| 8 | README wording | (a) as written; edit the voice freely |
| 9 | Sudo for the deploy user | (a) passwordless sudo |
| 10 | Root SSH login | (a) key-only root login kept as a fallback, for now |
| 11 | Public pages' `/api/session/properties` request | (a) keep it blocked |
| 12 | Image size (982 MB) | (a) leave it for now |

### Q1. The HTTPS address
- **What I found:** Caddy's current docs (its website repo on GitHub, `automatic-https.md`) say a hostname qualifies for a publicly trusted certificate only if it is "not an IP address". For an IP site address, Caddy serves a certificate from its own local CA, which browsers warn about. Its `tls` directive has an *experimental* ACME `profile` option. Let's Encrypt issues short-lived IP certificates, so an IP certificate might be configurable, but I couldn't verify that here.
- **Options:**
  - (a) A domain or subdomain you control: a DNS A record to the server, and Caddy gets and renews Let's Encrypt certificates by itself.
  - (b) The bare IP, with Caddy's self-signed certificate (browser warnings), or an untested ACME-profile configuration.
  - (c) HTTP only (`SITE_ADDRESS=:80`) while testing.
- **Recommendation:** (a). The files and runbook are written for it; (c) is fine for a first look.

### Q2. Server size and CPU type
- **What I found:** every image the stack uses publishes `linux/arm64` as well as `linux/amd64`:
  - `metabase/metabase:v0.64.3.4` (index digest `sha256:7804ce4e…`)
  - `postgres:16`
  - `caddy:2.11.7-alpine`
  - `python:3.12.15-slim-trixie`

  Not verified: building the pipeline image on arm64 (wheels for psycopg2-binary and pandas), or running anything on ARM. Memory at rest here was Metabase 1.375 GiB, Postgres 143 MiB and Caddy 12 MiB, plus a short pipeline run once a day.
- **Options:**
  - (a) x86, shared vCPU, 4 GB.
  - (b) ARM, 4 GB.
  - (c) x86, 8 GB.
- **Recommendation:** (a). It's what was verified. ARM looks viable, but rehearse a build there first.

### Q3. Metabase's Java heap
- **What I found:** with `-Xmx1536m`, Metabase used 1.375 GiB at rest on the demo data. On 4 GB that leaves about 2 GB for the JVM's off-heap memory, Postgres, the daily pipeline (pandas) and the OS.
- **Options:**
  - (a) 1536m.
  - (b) 1024m: safer for the box, but Metabase may slow down on heavy dashboards.
  - (c) 2048m: needs more RAM.
- **Recommendation:** (a), via `METABASE_JAVA_HEAP` in `.env`. Lower it to 1024m if `docker stats` or restarts show memory pressure (in the runbook's table).

### Q4. Dead-man's-switch service
- **What I found:** the runner follows the healthchecks.io convention (`<URL>` and `<URL>/fail`). Any service that accepts a GET works. A monitor on the same server can't detect the server being down.
- **Options:**
  - (a) healthchecks.io free tier, alerts to your own email.
  - (b) Another hosted cron monitor.
  - (c) None: check `make prod-health` by hand.
- **Recommendation:** (a): period 1 day, grace 2 hours, alerts to you (runbook section 13).

### Q5. Off-server copies and retention
- **What I found:** the nightly dumps sit on the server's own disk. If the server is lost, so are they. Demo-sized dumps are 300 KB and 1.2 MB; real ones will be bigger but small for a disk.
- **Options:**
  - (a) Copy one to the laptop with `scp` now and then (documented).
  - (b) Push automatically to a storage box or object storage. That needs new credentials on the server and a new script.
  - (c) The provider's paid server backups or snapshots.
- **Recommendation:** (a) now, and keep 14 (`BACKUP_KEEP`). Revisit (b) or (c) once the history is worth more than a few weekly copies.

### Q6. fail2ban
- **What I found:** with password login off and ufw on, fail2ban mostly reduces log noise from SSH scanners. It adds a package and a config to maintain.
- **Options:**
  - (a) Install it with the default sshd jail.
  - (b) Not now.
  - (c) Move SSH to another port.
- **Recommendation:** (b).

### Q7. A read-only copy on the laptop
- **What I found:** after the cut-over the laptop's database stops changing. Notebooks and report writing read `DATABASE_URL`, which points at the laptop's `jobmarket`.
- **Options:**
  - (a) No copy: use Metabase through the tunnel.
  - (b) Now and then, restore the newest server dump into the laptop's `jobmarket`. Use the rollback commands in `docs/deploy.md` section 10, without re-registering the task.
  - (c) A separate `jobmarket_copy` database, with notebooks pointed at it.
- **Recommendation:** (b). Nothing new is built: the rollback commands already do it. The rule is that the laptop task stays unregistered.

### Q8. README wording
- **What I found:** the pitch is in your voice, first person, and I kept that. Things you may want to word differently:
  - "Every day it pulls postings": true of the design, but only while the scheduled task is registered.
  - The roadmap says scheduling is "the daily runner plus a timer, not Prefect". Is dropping Prefect a decision you've made?
  - The roadmap marks phase 6 as partly done (kit ready, not deployed).
  - "Grouped numbers sit next to their n, with their caveats."
- **Options:**
  - (a) Keep it as written.
  - (b) Edit it.
- **Recommendation:** (a), and change the voice freely.

### Q9. Sudo for the deploy user
- **What I found:** the cut-over needs `sudo systemctl ...`, and `deploy` is in the docker group, which is already root-equivalent.
- **Options:**
  - (a) Passwordless sudo.
  - (b) Sudo with a password you set (`sudo passwd deploy` as root).
  - (c) No sudo; use `ssh root@...` for the few systemctl commands.
- **Recommendation:** (a), built. A sudo password adds friction, not safety, while docker access stays.

### Q10. Root SSH login
- **What I found:** bootstrap turns password login off for everyone and sets `PermitRootLogin prohibit-password`, which keeps root's key login as a fallback if something goes wrong with `deploy`.
- **Options:**
  - (a) Keep key-only root login.
  - (b) `PermitRootLogin no` once `deploy` has worked for a while.
  - (c) Disable it in bootstrap.
- **Recommendation:** (a) now, then (b).

### Q11. `/api/session/properties` on public pages
- **What I found:** a public dashboard page requests `/api/session/properties`. Caddy answers 404, and every card still renders (Playwright: no error text, no loading state). That endpoint, unauthenticated, reveals the instance's version and settings.
- **Options:**
  - (a) Keep it blocked.
  - (b) Allow it through Caddy.
- **Recommendation:** (a), built. Revisit only if a future Metabase version stops rendering without it; the provisioner's e2e test and the runbook's link check would show that.

### Q12. Image size
- **What I found:** the image is 982 MB because the runtime dependencies in `pyproject.toml` include jupyter, matplotlib and plotly, which the server never uses. It builds in under a minute on CI.
- **Options:**
  - (a) Leave it.
  - (b) Move notebook-only packages to an optional extra. This changes pyproject, so it's outside tonight's scope.
  - (c) A multi-stage build.
- **Recommendation:** (a) for now; (b) if disk or build time ever matters.

## What the owner must do

Nothing here touched a real server.

**On the laptop now:**

```powershell
# after merging the PR on GitHub
git checkout main
git pull
uv sync
```

Nothing else changes on the laptop until the cut-over. `docker-compose.yml`, the daily task and the local Metabase behave exactly as before. `scripts\windows\export_db.ps1` only reads, so you can try it any time.

**Then, from `docs/deploy.md`:**

- [ ] Decide Q1: pick a (sub)domain you control and make sure you can edit its DNS.
- [ ] Rent the server: sections 1 and 3 (spec, not price; check hetzner.com).
- [ ] SSH key: section 2.
- [ ] Bootstrap: section 5. It's untested on a real server, so read its output; it stops at the first error.
- [ ] `.env`: section 6. Leave the job-source keys empty for now.
- [ ] Start the stack: section 7. Metabase admin through the tunnel: section 8.
- [ ] Optional rehearsal: section 9, "Rehearsal".
- [ ] Cut-over day: section 9, steps 1–4. One machine per UTC day.
- [ ] Public links: section 9, step 5, then put one in the README's "Findings so far".
- [ ] Dead-man's switch (section 13), and an occasional off-server copy (section 11).

## Surprises

- **My final checks first ran on a stale image.** The stack's pipeline image had been built before the step-3 provisioner fix and before the ping commit. My first final pass showed the old behaviour: `--public-links` re-sent the setting, and links used the internal `http://metabase:3000`. I rebuilt from the final commit and re-ran every in-stack check: import, daily, health, provisioner twice, HTTP checks, Playwright, the e2e test and the backup round trip. The results above are from that run. On the server, `make prod-build` after every `git pull` prevents this (runbook section 12).
- **My own gate had a hole.** Its alembic step was an `&&` chain ending in `echo`, and `set -e` doesn't stop on a failure inside such a chain, so a failing migration would only have dropped the "alembic ok" line. Every earlier run had printed "alembic ok", so nothing slipped through. I split it into separate commands before the step-6 commit.
- **Docker's default logs never rotate.** Caddy writes its access log to stdout, so on a long-running server the json-file logs would eventually fill the disk. That's fix commit 8.
- **The old docs would have doubled the daily run.** `daily-operation.md` told the owner to add a cron job on the server, which would have run alongside the systemd timer. It now points to the runbook.
- **Metabase v0.64 quirks:**
  - `GET /api/setting/<key>` returns an empty 204.
  - Public pages request `/api/session/properties`.
  - "Too common" admin passwords are rejected.
  - Each instance also ships its own Sample Database and an "E-commerce Insights" example dashboard. Both are private, unreachable through Caddy, and can be deleted in Admin.
- **`docker compose cp` ignores umask.** It sets file modes from its tar stream (666), so dumps get an explicit `chmod 600`.
- **`requests` errors print host and path separately** ("url: /<token>/fail"), so masking only the full ping URL would have leaked the token. The path is masked too, and a test proves the leak without it.
- **PowerShell was obtainable after all.** The previous run's `apt-get install powershell` found nothing, but PowerShell 7.4.6 from its GitHub release ran here. So `export_db.ps1` was executed against a real compose `db` container, not only parse-checked. It ran on pwsh 7, not Windows PowerShell 5.1; ASCII only and no `>` keep it safe on 5.1.
- **Docker Hub returned 429** for anonymous pulls from this sandbox. Images came through `mirror.gcr.io` (Google's public Docker Hub cache), with digests checked against the tags. On your server compose pulls from Docker Hub normally.
- **This sandbox intercepts TLS**, so `pip` inside `docker build` needed the proxy's CA. The optional `extra_ca` build secret handles that without storing it in the image. Builds on the server or in CI don't need it.

## Suggested PR title

**Deploy kit for a small VPS: pipeline image, prod stack behind Caddy, systemd, backups, data move, runbook; README refresh**

<details>
<summary>PR description (ready to paste)</summary>

## Summary

Milestone D: everything needed to move the stack from the laptop to one small Linux server, built and verified in Docker with demo data. Nothing touched a real server.

- **CI:** `actions/checkout@v6` and `actions/setup-python@v6` (Node 24); a new `image` job builds and checks the pipeline image (no push, no login).
- **Pipeline image:** `Dockerfile` on `python:3.12.15-slim-trixie`, non-root, `pip install .`. It holds no `.env`, data, logs or tests (`scripts/verify_image.sh`).
- **Production stack** (`deploy/docker-compose.prod.yml`):
  - Postgres with no published port.
  - Metabase v0.64.3.4 with its app data in Postgres `metabase_app`, bound to 127.0.0.1 for SSH-tunnel admin.
  - Caddy forwarding only public-dashboard paths; everything else gets 404.
  - The pipeline as `docker compose run --rm pipeline ...`.
  - Rotating container logs.
  - `make prod-*` targets.
- **Scheduling:** systemd timers for the daily run (11:15 UTC) and backups (03:30 UTC).
- **Optional dead-man's-switch ping:** `HEALTHCHECK_PING_URL`; healthchecks.io convention; masked; never changes the exit code.
- **Backups:** `deploy/backup.sh` (pg_dump inside the container, 14 kept) and `deploy/restore.sh` (refuses a non-empty database without `--force`).
- **Moving the laptop's data:** `scripts/windows/export_db.ps1` (no `>` on binary output) and `deploy/import_db.sh` print the same row counts.
- **Server setup:** `deploy/bootstrap.sh` (Ubuntu 24.04, untested on a real server) and `docs/deploy.md`, a beginner runbook from Windows. It includes a cut-over with no lost day and no double Adzuna spend, rollback, backups, updating, and a "what can go wrong" table.
- **Provisioner fixes:** `--public-links` is idempotent on v0.64; printed links use `MB_SITE_URL`.
- **README:** "In three minutes", a Mermaid architecture diagram, "How it runs", "Findings so far", and an updated status and roadmap.

## Testing

- `pytest` with `TEST_DATABASE_URL`: 447 → **459 passed**, 1 skipped.
- `ruff check .` and `ruff format --check .` (0.17.2) clean; alembic round trip clean; `make views` applies 9 views, twice.
- shellcheck clean on all 7 shell scripts; `systemd-analyze verify` clean apart from the server-only path.
- The prod stack in Docker with demo data:
  - all 5 public dashboards render through Caddy (Playwright), with all 24 public card queries completed
  - 15 non-public paths return 404
  - Visa outlook has no public link
  - `db` publishes no port; Metabase's app data is in Postgres, not H2
  - the daily run (sources skipped) and the health check pass
  - the Metabase e2e test passes against it
- Backup/drop/restore and export/import round trips give matching row counts. `export_db.ps1` was parse-checked and run under PowerShell 7.4.6.
- No live job or government API was called.

Full results: `docs/overnight-deploy-kit.md`.

## Open questions

12 parked decisions are in `docs/overnight-deploy-kit.md`, each with the default that was built:
- the HTTPS address
- x86 vs ARM
- Metabase's heap
- the dead-man's-switch service
- off-server backups and retention
- fail2ban
- a laptop read-only copy
- README wording
- deploy's sudo
- root SSH login
- the blocked `/api/session/properties`
- image size

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01ATh4ABgiML8G58MzgJ36ZP

</details>
