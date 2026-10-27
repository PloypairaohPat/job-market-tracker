# Running on a server (Milestone D)

Today the laptop runs everything: Postgres in Docker, the daily task, and Metabase on localhost. A day the laptop is off is a day of snapshots lost for good, and the dashboards can't be public. This page moves the whole stack to one small Linux server. It's written for doing it from Windows, one step at a time.

What runs on the server (all in Docker, defined in `deploy/`):

| Piece | What it does | Reachable from |
|---|---|---|
| `db` | Postgres 16: the pipeline's database and Metabase's own app database (`metabase_app`) | the server's Docker network only; no port is published |
| `metabase` | the dashboards | `127.0.0.1:3000` on the server only; you reach it through an SSH tunnel |
| `caddy` | HTTPS in front of Metabase, forwarding **only** public-dashboard links | the internet, ports 80 and 443 |
| `pipeline` | the daily run, migrations, views, provisioning (`docker compose run --rm pipeline ...`) | nothing; it runs and exits |
| systemd timers | the daily run at 11:15 UTC, backups at 03:30 UTC | n/a |

Placeholders on this page: the server's address is written `203.0.113.10` and the domain `jobs.example.com`. Use your own.

Contents:

1. [What you need](#1-what-you-need)
2. [Create an SSH key](#2-create-an-ssh-key-on-the-laptop)
3. [Rent the server and log in](#3-rent-the-server-and-log-in)
4. [Choose the address](#4-choose-the-address-https)
5. [Bootstrap the server](#5-bootstrap-the-server)
6. [Fill in .env](#6-fill-in-env)
7. [Start the stack](#7-start-the-stack)
8. [Metabase admin through an SSH tunnel](#8-metabase-admin-through-an-ssh-tunnel)
9. [The cut-over](#9-the-cut-over)
10. [Rolling back to the laptop](#10-rolling-back-to-the-laptop)
11. [Backups and restore](#11-backups-and-restore)
12. [Updating](#12-updating)
13. [Dead-man's switch](#13-dead-mans-switch-optional)
14. [What can go wrong](#14-what-can-go-wrong)

## 1. What you need

- **A server:** a shared-vCPU **x86** server with **at least 4 GB RAM** running **Ubuntu 24.04**, with about 40 GB of disk or more. The roadmap says Hetzner Cloud; check the current price and availability on hetzner.com. Location is your choice.
- **For HTTPS:** ideally a domain or subdomain you control (see [step 4](#4-choose-the-address-https)).
- **On the laptop:** the repo with this page merged and pulled. Windows 10/11 already include `ssh`, `scp` and `ssh-keygen`.

## 2. Create an SSH key (on the laptop)

In PowerShell:

```powershell
ssh-keygen -t ed25519
```

- Press Enter to accept the default file (`$HOME\.ssh\id_ed25519`).
- Choose a passphrase. You'll type it when you connect.

This makes two files:

- `id_ed25519` is the **private** key. It never leaves the laptop. Never paste it anywhere.
- `id_ed25519.pub` is the **public** key, one line starting `ssh-ed25519`. This is the one you give the server.

Show the public key:

```powershell
Get-Content $HOME\.ssh\id_ed25519.pub
```

## 3. Rent the server and log in

1. In the provider's console (Hetzner Cloud: *Security → SSH keys*), add the public key: paste the whole `ssh-ed25519 ...` line.
2. Create the server:
   - image Ubuntu 24.04
   - an x86 shared-vCPU type with 4 GB RAM
   - your SSH key selected
3. Note its IPv4 address (here `203.0.113.10`).
4. First login, as root, from PowerShell:

   ```powershell
   ssh root@203.0.113.10
   ```

   The first time, it asks whether to trust the server's fingerprint. Type `yes`.

## 4. Choose the address (HTTPS)

Caddy is the only thing the internet can reach. What you put in `SITE_ADDRESS` decides how it serves HTTPS:

| Option | `.env` | Result |
|---|---|---|
| **a. A domain or subdomain you control (recommended)** | `SITE_ADDRESS=jobs.example.com`<br>`MB_SITE_URL=https://jobs.example.com` | Point a DNS **A record** for `jobs.example.com` at `203.0.113.10` at your DNS provider. Caddy then gets and renews a Let's Encrypt certificate by itself (ports 80 and 443 must be open; bootstrap opens them). |
| b. The bare IP address | `SITE_ADDRESS=203.0.113.10`<br>`MB_SITE_URL=https://203.0.113.10` | Let's Encrypt issues short-lived certificates for IP addresses, but Caddy's docs say IP addresses don't qualify for its automatic public certificates. It serves them with its own local certificate, so browsers show a warning. Not recommended. |
| c. HTTP only, while testing | `SITE_ADDRESS=:80`<br>`MB_SITE_URL=http://203.0.113.10` | No certificate and no encryption. Fine for a first look; don't share links like this. |

This is still an open question (see `docs/overnight-deploy-kit.md`). Option (a) is the default the files are written for.

## 5. Bootstrap the server

Still logged in as root on the server:

```bash
curl -fsSLO https://raw.githubusercontent.com/PloypairaohPat/job-market-tracker/main/deploy/bootstrap.sh
less bootstrap.sh                                   # read it first; q quits
bash bootstrap.sh "$(head -n 1 ~/.ssh/authorized_keys)"
```

`~/.ssh/authorized_keys` on a fresh server holds the key you picked when creating it, so `head -n 1` passes that key. You can also paste it yourself: `bash bootstrap.sh "ssh-ed25519 AAAA... you@laptop"`.

`deploy/bootstrap.sh` (read its header for details):

1. installs Docker Engine (from Docker's own apt repository), git, make, ufw and unattended-upgrades
2. creates the user **deploy** with your key, in the docker group, with sudo
3. turns off SSH password login; root keeps key-only login as a fallback
4. firewall: allows 22, 80 and 443 in, and denies everything else
5. turns on automatic security updates
6. clones the repo to `/home/deploy/job-market-tracker` and creates `.env` from `deploy/.env.example` (mode 600, readable only by deploy). It also creates `/var/backups/jobmarket`, installs the systemd units and enables the **backup** timer. The **daily** timer stays off until the cut-over.

Running it again is safe. It has not been tested on a real server yet, so read its output; it stops at the first error.

**Before you close the root session**, open a second PowerShell window and check that you can log in as deploy:

```powershell
ssh deploy@203.0.113.10
```

From now on, always log in as `deploy`.

## 6. Fill in .env

```bash
cd ~/job-market-tracker
nano .env
```

In nano: arrow keys move; **Ctrl+O** then **Enter** saves; **Ctrl+X** exits.

| Variable | What to put |
|---|---|
| `POSTGRES_PASSWORD` | a new random password (below) |
| `METABASE_APP_DB_PASSWORD` | another new random password |
| `SITE_ADDRESS`, `MB_SITE_URL` | from [step 4](#4-choose-the-address-https) |
| `METABASE_ADMIN_EMAIL` | your email: the Metabase admin login |
| `METABASE_ADMIN_PASSWORD` | another new random password: you log in to Metabase with it |
| `METABASE_READER_PASSWORD` | another new random password (the read-only role the dashboards use) |
| `METABASE_JAVA_HEAP` | leave `1536m` |
| `ADZUNA_*`, `USAJOBS_*` keys | **leave empty for now.** You copy them from the laptop's `.env` during the cut-over. Until then nothing on the server can spend Adzuna calls. |
| `HEALTHCHECK_PING_URL` | empty for now ([step 13](#13-dead-mans-switch-optional)) |
| `BACKUP_DIR` | leave `/var/backups/jobmarket` |

Make each password on the server with:

```bash
openssl rand -hex 24
```

Copy the output into `.env`. Use a different one for each line, and only letters and digits: the passwords go into connection URLs, and Metabase rejects common ones.

## 7. Start the stack

```bash
make prod-build     # builds the pipeline image (a few minutes the first time)
make prod-up        # starts db, metabase and caddy and waits until they're healthy
make prod-ps        # what's running, and which ports are published
```

The first start of Metabase takes a minute or two. On a fresh volume, Postgres creates Metabase's app database `metabase_app` by itself.

Check:

- `make prod-ps` shows ports only for caddy (80, 443) and metabase (`127.0.0.1:3000`). **db shows none.**
- Opening `https://jobs.example.com/` in a browser gives an empty page or the browser's own "HTTP ERROR 404". That's correct: only public-dashboard links get through.

The database is still empty. The cut-over fills it with the laptop's history.

## 8. Metabase admin through an SSH tunnel

Metabase's login page is never reachable from the internet. To administer it, open a tunnel from the laptop:

```powershell
ssh -L 3000:localhost:3000 deploy@203.0.113.10
```

Keep that window open, and browse to **http://localhost:3000** on the laptop. Log in with `METABASE_ADMIN_EMAIL` and `METABASE_ADMIN_PASSWORD`.

- If the laptop's own Metabase is using port 3000, stop it first (`docker compose --profile bi stop metabase`), or tunnel to another port: `ssh -L 3001:localhost:3000 deploy@203.0.113.10`, then http://localhost:3001.
- If you see Metabase's setup wizard, the provisioner hasn't run yet. Don't fill the wizard in; run the import (cut-over step 2) or `make prod-provision`, which sets Metabase up from `.env`.

## 9. The cut-over

**The rule: on any UTC day, exactly one machine runs ingestion.**

- If neither runs, that day is lost for good.
- If both run, Adzuna calls are spent twice. The budget guard (`src/ingestion/budget.py`) only counts calls recorded in its *own* database: the laptop and the server would each think they had the whole 1,000-call month.

The import carries the month's calls so far over to the server, so the server's guard starts from the right number. Calls the laptop makes *after* the export are invisible to the server.

The timings: the laptop task runs at 07:15 US Eastern, which is 11:15 UTC in summer and 12:15 UTC in winter. The server timer runs at 11:15 UTC. Check today's UTC date on the server with `date -u +%F`.

### Rehearsal (optional, recommended)

On any day before the real one, you can do step 2 below without unregistering the laptop task. Import, then look at the dashboards through the tunnel. Nothing on the server ingests yet: the timer is off and the API keys are empty.

On the real day, add `--force` to `deploy/import_db.sh` to replace the rehearsal data.

### Cut-over day

**1. Let the laptop's daily run finish, then turn the laptop task off.** In PowerShell, in the repo:

```powershell
Get-ScheduledTaskInfo -TaskName JobMarketTracker-Daily     # LastRunTime is today, LastTaskResult 0
uv run python -m src.pipeline.health
.\scripts\windows\register_daily_task.ps1 -Unregister
```

**2. Export, copy and import.**

```powershell
.\scripts\windows\export_db.ps1
```

It prints the dump's path, its SHA256 and four counts (jobs, job_snapshots, ingestion_runs, latest snapshot_date). Keep that window open. It writes the dump inside the db container and copies it out; never save a dump with `>` in PowerShell, which corrupts it.

Copy it to the server, using the path and name it printed:

```powershell
scp "$HOME\jobmarket-export\jobmarket_<stamp>.dump" deploy@203.0.113.10:~/
```

On the server:

```bash
sha256sum ~/jobmarket_<stamp>.dump            # must equal the SHA256 the export printed
cd ~/job-market-tracker
deploy/import_db.sh ~/jobmarket_<stamp>.dump  # add --force if you rehearsed
```

`deploy/import_db.sh`:

- restores the dump into a fresh `jobmarket` database
- runs migrations, the views and the read-only role inside the pipeline image
- builds the dashboards
- prints the same four counts

**All four lines must match the export.** If they don't, stop here and [roll back](#10-rolling-back-to-the-laptop). Nothing is lost: the laptop still has everything.

**3. Turn the server's daily run on.** Copy `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `USAJOBS_API_KEY` and `USAJOBS_USER_AGENT_EMAIL` from the laptop's `.env` (open it in Notepad) into the server's `.env` with `nano .env`. Then:

```bash
sudo systemctl enable --now jobmarket-daily.timer
systemctl list-timers jobmarket-daily.timer       # NEXT: 11:15 UTC
```

Enabling the timer after 11:15 UTC doesn't start a run today: the first one is tomorrow at 11:15 UTC.

Then decide about **today**, from the "latest snapshot_date" the export printed:

- **It is today's UTC date:** the laptop already ran today. Do nothing; the timer runs tomorrow.
- **It is earlier** (the laptop missed today): run once now, and watch it:

  ```bash
  sudo systemctl start jobmarket-daily.service      # waits until the run ends (a few minutes)
  sudo journalctl -u jobmarket-daily.service -e     # the run's log; q quits
  ```

**4. The next day,** after about 11:45 UTC:

```bash
make prod-health                                   # every line PASS (or an expected WARN)
sudo journalctl -u jobmarket-daily.service -S yesterday   # the run's log
ls -lh /var/backups/jobmarket                      # last night's backup
```

Then open the **Ingestion health** dashboard through the tunnel and check the new day is there.

Delete the dump from the laptop (`$HOME\jobmarket-export`) and the server (`rm ~/jobmarket_*.dump`) once you're happy: it holds the whole database.

**5. Only then, turn on public links:**

```bash
make prod-provision ARGS=--public-links
```

It prints one `https://jobs.example.com/public/dashboard/...` link per public dashboard. **Visa outlook** never gets one (it's your job search). Open each link in a private browser window to check it works without logging in. Put the Ingestion health or Market overview link in the README's "Findings so far" line.

## 10. Rolling back to the laptop

If the server fails after the cut-over, the laptop can take over again. Use the server's latest data, so the days it collected aren't lost:

1. **Stop the server's daily run** (if you can still log in), so only one machine ingests:

   ```bash
   sudo systemctl disable --now jobmarket-daily.timer
   ```

2. **Bring the server's data back** to the laptop. You need the newest dump in `/var/backups/jobmarket`, or a fresh one from `deploy/backup.sh`.

   Copy it, in PowerShell, in the repo:

   ```powershell
   scp deploy@203.0.113.10:/var/backups/jobmarket/jobmarket_<stamp>.dump $HOME\jobmarket-export\
   ```

   Replace the laptop's database with it:

   ```powershell
   docker compose up -d db
   docker compose cp "$HOME\jobmarket-export\jobmarket_<stamp>.dump" db:/tmp/restore.dump
   docker compose exec -T db dropdb -U postgres --force jobmarket
   docker compose exec -T db createdb -U postgres jobmarket
   docker compose exec -T db pg_restore -U postgres -d jobmarket --no-owner --no-privileges /tmp/restore.dump
   docker compose exec -T db rm /tmp/restore.dump
   uv run alembic upgrade head
   uv run python scripts/apply_views.py
   uv run python -m src.dashboard.reader_role     # only if you use Metabase on the laptop
   ```

   If the server is gone and its backups with it, skip this step. The laptop still has everything up to the export; only the days since then are lost.

3. **Re-register the laptop task:**

   ```powershell
   .\scripts\windows\register_daily_task.ps1
   ```

   If the server already ran today (UTC), the laptop must not run again today. The task's first run is tomorrow at 07:15; don't start it by hand.

To go back to the server later, repeat the cut-over (import with `--force`).

## 11. Backups and restore

The backup timer (03:30 UTC, nowhere near the 11:15 run) runs `deploy/backup.sh`:

- dumps `jobmarket` and `metabase_app` into `/var/backups/jobmarket` as `<db>_YYYYMMDDTHHMMSSZ.dump` (UTC)
- keeps the newest 14 of each
- deletes only files with exactly that name pattern

```bash
systemctl list-timers jobmarket-backup.timer      # when it runs next
ls -lh /var/backups/jobmarket                     # the dumps
sudo journalctl -u jobmarket-backup.service -e    # its log
deploy/backup.sh                                  # a backup right now
```

**These backups live on the same disk as the database.** If the server is lost, so are they. Copy one to the laptop now and then:

```powershell
scp deploy@203.0.113.10:/var/backups/jobmarket/jobmarket_<stamp>.dump $HOME\jobmarket-export\
```

Off-server copies are an open question (`docs/overnight-deploy-kit.md`).

**Restore the pipeline database** (replaces it; the counts print at the end):

```bash
deploy/import_db.sh /var/backups/jobmarket/jobmarket_<stamp>.dump --force
```

**Restore Metabase's app database.** This keeps the public links' addresses: rebuilding Metabase from scratch with the provisioner works too, but gives every public dashboard a new link.

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file .env stop metabase
deploy/restore.sh /var/backups/jobmarket/metabase_app_<stamp>.dump metabase_app --force
make prod-up
```

`deploy/restore.sh` refuses to overwrite a database that has tables unless you add `--force`.

## 12. Updating

When the repo has changed (do this away from 11:15 UTC):

```bash
cd ~/job-market-tracker
git pull
make prod-build                         # rebuild the pipeline image
make prod-up                            # recreates containers whose settings changed
make prod-migrate                       # database migrations
make prod-views                         # the SQL views
make prod-grant                         # the read-only role (after new views)
make prod-provision ARGS=--public-links # dashboards; drop ARGS until public links are on
```

- If `deploy/Caddyfile` changed, restart Caddy: `docker compose -f deploy/docker-compose.prod.yml --env-file .env restart caddy`.
- If `deploy/systemd/` changed, re-run `sudo bash deploy/bootstrap.sh "$(head -n 1 ~/.ssh/authorized_keys)"`. It reinstalls the units and leaves `.env` and the daily timer alone.
- If `deploy/.env.example` gained a variable, add it to `.env`.

## 13. Dead-man's switch (optional)

`make prod-health` only tells you something when you run it. If the server dies or the timer stops, nothing warns you. A dead-man's switch does: the daily run pings a URL after every run, and the service emails you when a ping doesn't arrive.

The suggested service is healthchecks.io's free tier (still an open question):

1. Sign up, and create a check with **period 1 day** and **grace 2 hours**.
2. Copy its ping URL into `.env` as `HEALTHCHECK_PING_URL=...`. Nothing needs restarting: each run reads `.env`.
3. To test, ping it once by hand: `curl -fsS -m 10 "<your ping URL>"`. The check turns green.

After each run, the pipeline sends a GET:

- to the URL when the run succeeded
- to `<URL>/fail` when a step failed

A ping that can't be delivered is logged and never changes the run's result. The URL is masked as `***` in logs. If the variable is empty, nothing is sent.

## 14. What can go wrong

| Symptom | Likely cause | What to do |
|---|---|---|
| `Permission denied (publickey)` | wrong user, or the key isn't on the server | Log in as `deploy`, not root. Try `ssh -i $HOME\.ssh\id_ed25519 deploy@203.0.113.10`. Root still works with your key, as a fallback. |
| Locked out completely | SSH misconfigured | Use the provider's web console (Hetzner Cloud has one on the server's page). |
| `required variable POSTGRES_PASSWORD is missing a value` (or another variable) | an empty value in `.env` | `nano .env` and fill it in. |
| Browser certificate warning, or Caddy can't get a certificate | DNS doesn't point at the server yet, or `SITE_ADDRESS` is an IP | Check the A record; wait for DNS; look at `make prod-logs` (caddy lines). |
| A public link shows "404" | the link doesn't start with `/public/dashboard/`, or `MB_SITE_URL` is wrong | Re-run `make prod-provision ARGS=--public-links` and use the links it prints. |
| Metabase keeps restarting or is "unhealthy" | out of memory | `free -h` and `docker stats`. Lower `METABASE_JAVA_HEAP` (e.g. `1024m`), then `make prod-up`; or move to a bigger server. |
| The daily run failed | an API error, an expired key, or a code error | `sudo journalctl -u jobmarket-daily.service -e` and `make prod-health`. Fix it before 11:15 UTC tomorrow. A missed day can't be backfilled. |
| Import counts don't match the export | the export or copy went wrong | Don't continue. Check the SHA256, export again, and if in doubt [roll back](#10-rolling-back-to-the-laptop). |
| Disk full | backups or old images | `df -h`, `du -sh /var/backups/jobmarket`, `docker system df`; `docker image prune` removes unused images. |
| Both machines ran on the same UTC day | the laptop task is still registered | `Get-ScheduledTask -TaskName JobMarketTracker-Daily` must say it doesn't exist. Unregister it. |
| `$'\r': command not found` | a script was edited on Windows (CRLF line endings) | Get scripts on the server with `git pull`, never by copying them from Windows. |
| You added `ports:` to `db` | n/a | Remove it. **Docker-published ports bypass the ufw firewall**: Postgres would be open to the internet. |
