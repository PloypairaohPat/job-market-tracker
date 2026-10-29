"""Is this machine set up right? A read-only check of the laptop setup.

Run:  python -m src.doctor [--json]      (or: make doctor)

It never changes anything and never prints a secret value: environment
variables are named, never shown, and the database is shown as host:port.
Each check prints PASS, WARN, FAIL, SKIP or INFO, a one-line finding and,
when something is wrong, the exact command to fix it (Windows PowerShell,
plus the POSIX form where it differs). In this order:

   1 .env             present, readable (no NUL bytes from PowerShell `>>`),
                      DATABASE_URL using postgresql+psycopg2://, and which
                      Adzuna / USAJobs variables are set (names only)
   2 database         one quick connection attempt; if it fails, every check
                      that needs the database is SKIPped
   3 migrations       the database's alembic revision is the code's head
   4 views            every sql/views/*.sql exists in the database
   5 daily clock      health checks H1, H2 and H7, the streak, snapshot days
   6 scheduled task   Windows only: the JobMarketTracker-Daily task's last
                      run, last result and next run
   7 LCA data         loaded? v_lca_coverage per fiscal year; a non-latest FY
                      with fewer than 12 months; files in data/lca/ whose FY
                      isn't loaded
   8 file placement   untracked .xlsx / .csv / .dump / .log outside data/ and
                      logs/, where they could be committed by mistake
   9 virtualenv       another virtualenv active (INFO: harmless)
  10 uv.lock          untracked uv.lock (INFO: committing it is undecided)

Exit code 1 if any check FAILs, else 0. Every outside call (the database,
schtasks, git) is injectable, so the tests use fakes.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Connection, Engine

ROOT = Path(__file__).resolve().parents[1]
TASK_NAME = "JobMarketTracker-Daily"
DRIVER_PREFIX = "postgresql+psycopg2://"
CONNECT_TIMEOUT_SECONDS = 5
SOURCE_VARS = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "USAJOBS_API_KEY", "USAJOBS_USER_AGENT_EMAIL")
STRAY_SUFFIXES = (".xlsx", ".csv", ".dump", ".log")
TASK_NOT_RUN_YET = 267011  # SCHED_S_TASK_HAS_NOT_RUN (0x41303)

PASS, WARN, FAIL, SKIP, INFO = "PASS", "WARN", "FAIL", "SKIP", "INFO"
_RANK = {PASS: 0, INFO: 0, SKIP: 0, WARN: 1, FAIL: 2}

DOCKER_FIX = 'open Docker Desktop and wait for "Engine running", then: docker compose up -d db'


@dataclass
class Finding:
    id: int
    name: str
    status: str
    detail: str
    fix: str = ""  # Windows PowerShell
    fix_posix: str = ""  # only where it differs


@dataclass
class Context:
    """Everything a check reads from the outside world, injectable for tests."""

    root: Path = ROOT
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    platform: str = sys.platform
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    engine_factory: Callable[[str], Engine] | None = None  # default: _engine
    run_schtasks: Callable[[], tuple[int, str]] | None = None  # default: _schtasks
    git_status: Callable[[Path], str | None] | None = None  # default: _git_status
    # filled in by the checks as they go
    env_values: dict[str, str] = field(default_factory=dict)
    database_url: str = ""

    def __post_init__(self) -> None:
        self.engine_factory = self.engine_factory or _engine
        self.run_schtasks = self.run_schtasks or _schtasks
        self.git_status = self.git_status or _git_status


# --------------------------------------------------------------------- #
# the outside world (replaced by fakes in tests)


def _engine(database_url: str) -> Engine:
    return create_engine(database_url, connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS})


def _schtasks() -> tuple[int, str]:
    done = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return done.returncode, done.stdout + done.stderr


def _git_status(root: Path) -> str | None:
    """`git status --porcelain`, every untracked file listed; None if git can't say."""
    try:
        done = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def where(database_url: str) -> str:
    url = make_url(database_url)
    return f"{url.host or 'localhost'}:{url.port or 5432}"


def _win(path: str) -> str:
    return path.replace("/", "\\")


# --------------------------------------------------------------------- #
# 1 .env


def check_env(ctx: Context) -> Finding:
    name = ".env"
    path = ctx.root / ".env"
    if not path.exists():
        if ctx.environ.get("DATABASE_URL"):
            ctx.database_url = ctx.environ["DATABASE_URL"]
            return _env_finding(ctx, "no .env file; DATABASE_URL comes from the environment")
        return Finding(
            1,
            name,
            FAIL,
            "no .env file, and DATABASE_URL isn't set",
            fix='Copy-Item ".env.example" ".env"; notepad ".env"',
            fix_posix='cp ".env.example" ".env"   # then edit it',
        )
    raw = path.read_bytes()
    if b"\x00" in raw:
        return Finding(
            1,
            name,
            FAIL,
            ".env contains NUL bytes (saved as UTF-16 by PowerShell echo or >>), "
            "so Python can't read it",
            fix='re-save .env as UTF-8 in Notepad: notepad ".env", then File > Save As > '
            "Encoding: UTF-8",
        )
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return Finding(
            1,
            name,
            FAIL,
            ".env isn't UTF-8",
            fix='re-save .env as UTF-8 in Notepad: notepad ".env", then File > Save As > '
            "Encoding: UTF-8",
        )
    ctx.env_values = {k: v or "" for k, v in dotenv_values(stream=io.StringIO(decoded)).items()}
    # like python-dotenv: a variable already in the environment wins over .env
    ctx.database_url = ctx.environ.get("DATABASE_URL") or ctx.env_values.get("DATABASE_URL", "")
    return _env_finding(ctx, ".env found")


def _env_finding(ctx: Context, found: str) -> Finding:
    name = ".env"
    url = ctx.database_url
    example = DRIVER_PREFIX + "postgres:postgres@localhost:5432/jobmarket"
    if not url:
        return Finding(
            1,
            name,
            FAIL,
            f"{found}, but DATABASE_URL isn't set",
            fix=f'notepad ".env"   # add the line DATABASE_URL={example}',
        )
    if not url.startswith(DRIVER_PREFIX):
        scheme = url.split("://", 1)[0] + "://" if "://" in url else "(no scheme)"
        bad = f"{found}, but DATABASE_URL starts with {scheme}, not {DRIVER_PREFIX}"
        ctx.database_url = ""  # the database checks can't use it
        return Finding(
            1,
            name,
            FAIL,
            bad,
            fix=f'notepad ".env"   # make it DATABASE_URL={example}',
        )
    values = {**ctx.env_values, **ctx.environ}
    have = [v for v in SOURCE_VARS if values.get(v)]
    missing = [v for v in SOURCE_VARS if not values.get(v)]
    detail = f"{found}; DATABASE_URL uses {DRIVER_PREFIX}; set: {', '.join(have) or 'none'}"
    if missing:
        has_file = (ctx.root / ".env").exists()
        return Finding(
            1,
            name,
            WARN,
            f"{detail}; not set: {', '.join(missing)} (that source's daily ingestion will fail)",
            fix=("" if has_file else 'Copy-Item ".env.example" ".env"; ')
            + 'notepad ".env"   # fill in the missing names (see .env.example)',
            fix_posix="" if has_file else 'cp ".env.example" ".env"   # then fill in the names',
        )
    return Finding(1, name, PASS, detail)


# --------------------------------------------------------------------- #
# 2 database


def check_database(ctx: Context) -> tuple[Finding, Connection | None]:
    name = "database"
    if not ctx.database_url:
        return Finding(2, name, SKIP, "no usable DATABASE_URL (see check 1)"), None
    address = where(ctx.database_url)
    conn = None
    try:
        conn = ctx.engine_factory(ctx.database_url).connect()
        conn.execute(text("select 1"))
    except Exception as exc:
        if conn is not None:
            conn.close()
        return (
            Finding(
                2,
                name,
                FAIL,
                f"not reachable at {address} ({type(exc).__name__})",
                fix=DOCKER_FIX,
            ),
            None,
        )
    return Finding(2, name, PASS, f"reachable at {address}"), conn


def _needs_db(id_: int, name: str) -> Finding:
    return Finding(id_, name, SKIP, "needs the database (see check 2)")


# --------------------------------------------------------------------- #
# 3 migrations


def check_migrations(ctx: Context, conn: Connection) -> Finding:
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    name = "migrations"
    config = Config(str(ctx.root / "alembic.ini"))
    config.set_main_option("script_location", str(ctx.root / "migrations"))
    heads = set(ScriptDirectory.from_config(config).get_heads())
    current = set(MigrationContext.configure(conn).get_current_heads())
    fix = "uv run alembic upgrade head"
    if current == heads:
        return Finding(3, name, PASS, f"at head {', '.join(sorted(heads))}")
    if not current:
        return Finding(3, name, FAIL, "no migration has been applied", fix=fix)
    return Finding(
        3,
        name,
        FAIL,
        f"database at {', '.join(sorted(current))}, code at {', '.join(sorted(heads))}",
        fix=fix,
    )


# --------------------------------------------------------------------- #
# 4 views


def check_views(ctx: Context, conn: Connection) -> Finding:
    name = "views"
    expected = sorted(p.stem for p in (ctx.root / "sql" / "views").glob("*.sql"))
    present = set(
        conn.execute(text("select viewname from pg_views where schemaname = 'public'")).scalars()
    )
    missing = [v for v in expected if v not in present]
    if missing:
        return Finding(
            4,
            name,
            FAIL,
            f"{len(missing)} of {len(expected)} views missing: {', '.join(missing)}",
            fix="uv run python scripts/apply_views.py",
        )
    return Finding(4, name, PASS, f"all {len(expected)} views exist")


# --------------------------------------------------------------------- #
# 5 daily clock


def check_daily_clock(ctx: Context, conn: Connection) -> Finding:
    from sqlalchemy.orm import Session

    from src.pipeline.health import run_health

    name = "daily clock"
    budget = int(ctx.environ.get("ADZUNA_MONTHLY_CALL_BUDGET") or 1000)
    with Session(bind=conn) as session:
        report = run_health(session, ctx.now, budget)
        session.rollback()  # read-only
    picked = [c for c in report.checks if c.id in ("H1", "H2", "H7")]
    progress = {c.name: c.detail for c in report.progress}
    worst = max((c.status for c in picked), key=lambda s: _RANK[s], default=PASS)
    parts = [
        f"{_label(c.id, c.name)} {c.status}" + (f" ({c.detail})" if c.status != PASS else "")
        for c in picked
    ]
    detail = (
        "; ".join(parts)
        + f"; streak {progress.get('current streak', '?')}; "
        + f"snapshot days {progress.get('snapshot days', '?')}"
    )
    if worst == PASS:
        return Finding(5, name, PASS, detail)
    return Finding(
        5,
        name,
        worst,
        detail,
        fix="Start-ScheduledTask -TaskName JobMarketTracker-Daily   "
        '# then see docs\\daily-operation.md, "If a day was missed"',
        fix_posix='./scripts/run_daily.sh   # then see docs/daily-operation.md, "If a day was missed"',
    )


def _label(check_id: str, name: str) -> str:
    """'H1' + 'run freshness (adzuna)' -> 'H1 adzuna'; 'H2' + '...' -> 'H2'."""
    source = name.partition("(")[2].rstrip(")")
    return f"{check_id} {source}" if source else check_id


# --------------------------------------------------------------------- #
# 6 scheduled task


def parse_schtasks(output: str) -> dict[str, str]:
    """`Key: value` lines of `schtasks /V /FO LIST` (first occurrence wins)."""
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and key.strip() not in fields:
            fields[key.strip()] = value.strip()
    return fields


def check_scheduled_task(ctx: Context) -> Finding:
    name = "scheduled task"
    if not ctx.platform.startswith("win"):
        return Finding(6, name, SKIP, "not Windows (on Linux, cron runs scripts/run_daily.sh)")
    register = ".\\scripts\\windows\\register_daily_task.ps1"
    code, output = ctx.run_schtasks()
    if code != 0:
        return Finding(6, name, FAIL, f"no task named {TASK_NAME}", fix=register)
    fields = parse_schtasks(output)
    last_run = fields.get("Last Run Time", "?")
    next_run = fields.get("Next Run Time", "?")
    raw = fields.get("Last Result", "")
    when = f"last run {last_run}, next run {next_run}"
    try:
        result = int(raw)
    except ValueError:
        return Finding(
            6, name, WARN, f"couldn't read the last result from schtasks ({when})", fix=register
        )
    if result == 0:
        return Finding(6, name, PASS, f"{when}; last result 0 (success)")
    if result == TASK_NOT_RUN_YET:
        return Finding(
            6,
            name,
            PASS,
            f"{when}; last result {TASK_NOT_RUN_YET}: hasn't run yet since it was registered",
        )
    meaning = {
        1: "a step failed",
        2: "the database was unreachable",
    }.get(result, "Task Scheduler's own error code")
    return Finding(
        6,
        name,
        WARN,
        f"{when}; last result {result} ({meaning})",
        fix='Get-Content "logs\\daily-YYYY-MM-DD.log" -Tail 25   '
        '# the latest log; see docs\\daily-operation.md, "Exit codes"',
    )


# --------------------------------------------------------------------- #
# 7 LCA data

_FY_IN_NAME = re.compile(r"FY\s*_?(\d{4})", re.IGNORECASE)


def fiscal_months(fiscal_year: int) -> list[date]:
    """First of each month of the federal FY: Oct of FY-1 through Sep of FY."""
    return [date(fiscal_year - (m >= 10), m, 1) for m in (*range(10, 13), *range(1, 10))]


def check_lca(ctx: Context, conn: Connection) -> Finding:
    name = "LCA data"
    readme = "follow src\\visa\\README.md, steps 1-3: download into data\\lca\\, then load"
    n = conn.execute(text("select count(*) from lca_cases")).scalar_one()
    if not n:
        return Finding(
            7,
            name,
            WARN,
            "lca_cases is empty: Report 3's sponsorship sections say 'LCA data not loaded'",
            fix=readme,
            fix_posix="follow src/visa/README.md, steps 1-3",
        )
    coverage = conn.execute(
        text(
            "select fiscal_year, n_cases, min_decision_date, max_decision_date, "
            "n_months_with_decisions from v_lca_coverage order by fiscal_year"
        )
    ).all()
    months = {
        (fy, month)
        for fy, month in conn.execute(
            text(
                "select distinct fiscal_year, date_trunc('month', decision_date)::date "
                "from lca_cases where decision_date is not null"
            )
        )
    }
    latest = max(r.fiscal_year for r in coverage)
    problems, fixes = [], []
    for r in coverage:
        if r.fiscal_year != latest and r.n_months_with_decisions < 12:
            gone = [m for m in fiscal_months(r.fiscal_year) if (r.fiscal_year, m) not in months]
            listed = ", ".join(f"{m:%Y-%m}" for m in gone)
            problems.append(
                f"FY{r.fiscal_year} has {r.n_months_with_decisions} of 12 months"
                + (f" (missing {listed})" if listed else "")
            )
    loaded = {r.fiscal_year for r in coverage}
    lca_dir = ctx.root / "data" / "lca"
    for path in sorted(lca_dir.glob("*")) if lca_dir.is_dir() else []:
        found = _FY_IN_NAME.search(path.name)
        if path.suffix.lower() in (".xlsx", ".csv") and found and int(found[1]) not in loaded:
            fy = found[1]
            problems.append(f"data/lca/{path.name} looks unloaded (FY{fy} not in lca_cases)")
            fixes.append(
                f'uv run python -m src.visa.lca_loader --file "data\\lca\\{path.name}" '
                f"--fiscal-year {fy}"
            )
    summary = "; ".join(
        f"FY{r.fiscal_year}: {r.n_cases:,} cases, {r.n_months_with_decisions} months "
        f"({r.min_decision_date} to {r.max_decision_date})"
        for r in coverage
    )
    if problems:
        return Finding(
            7,
            name,
            WARN,
            f"{summary}. " + "; ".join(problems),
            fix=" ; ".join(fixes) or readme,
            fix_posix="" if fixes else "follow src/visa/README.md, steps 1-3",
        )
    return Finding(7, name, PASS, summary)


# --------------------------------------------------------------------- #
# 8 file placement


def stray_files(porcelain: str) -> list[str]:
    """Untracked data-ish files outside data/ and logs/ (git paths, '/' separated)."""
    out = []
    for line in porcelain.splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip().strip('"')
        if path.startswith(("data/", "logs/")):
            continue
        if path.lower().endswith(STRAY_SUFFIXES):
            out.append(path)
    return out


def _destination(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".log"):
        return "logs"
    if "lca" in Path(lower).name and lower.endswith((".xlsx", ".csv")):
        return "data/lca"
    return "data"


def check_file_placement(ctx: Context) -> Finding:
    name = "file placement"
    porcelain = ctx.git_status(ctx.root)
    if porcelain is None:
        return Finding(8, name, SKIP, "git status unavailable (not a git checkout?)")
    stray = stray_files(porcelain)
    if not stray:
        return Finding(
            8, name, PASS, "no untracked .xlsx, .csv, .dump or .log outside data/, logs/"
        )
    fixes = [
        f'New-Item -ItemType Directory -Force "{_win(_destination(p))}" | Out-Null; '
        f'Move-Item "{_win(p)}" "{_win(_destination(p))}\\"'
        for p in stray
    ]
    posix = [f'mkdir -p "{_destination(p)}" && mv "{p}" "{_destination(p)}/"' for p in stray]
    return Finding(
        8,
        name,
        FAIL,
        f"{len(stray)} untracked file(s) that git could commit by mistake: {', '.join(stray)}; "
        "move it into data\\... (gitignored)",
        fix=" ; ".join(fixes),
        fix_posix=" ; ".join(posix),
    )


# --------------------------------------------------------------------- #
# 9 virtualenv, 10 uv.lock


def check_virtualenv(ctx: Context) -> Finding:
    name = "virtualenv"
    active = ctx.environ.get("VIRTUAL_ENV", "")
    if not active:
        return Finding(9, name, PASS, "no other virtualenv active")
    project = ctx.root / ".venv"
    same = os.path.normcase(os.path.abspath(active)) == os.path.normcase(str(project.absolute()))
    if same:
        return Finding(9, name, PASS, "the project's .venv is active")
    return Finding(
        9,
        name,
        INFO,
        "another virtualenv is active, so uv warns that VIRTUAL_ENV doesn't match .venv: "
        "harmless; uv uses .venv",
        fix="deactivate   # or untick VS Code's python.terminal.activateEnvironment",
    )


def check_uv_lock(ctx: Context) -> Finding:
    name = "uv.lock"
    porcelain = ctx.git_status(ctx.root)
    if porcelain is None:
        return Finding(10, name, SKIP, "git status unavailable")
    if any(line[3:].strip() == "uv.lock" for line in porcelain.splitlines() if line[:3] == "?? "):
        return Finding(
            10,
            name,
            INFO,
            "uv.lock is untracked. Whether to commit it is an open decision; leave it as is",
        )
    tracked = (ctx.root / "uv.lock").exists()
    return Finding(10, name, PASS, "uv.lock is tracked" if tracked else "no uv.lock")


# --------------------------------------------------------------------- #


def run_checks(ctx: Context) -> list[Finding]:
    findings = [_safely(1, ".env", check_env, ctx)]
    db, conn = check_database(ctx)
    findings.append(db)
    try:
        for id_, name, check in (
            (3, "migrations", check_migrations),
            (4, "views", check_views),
            (5, "daily clock", check_daily_clock),
        ):
            findings.append(_safely(id_, name, check, ctx, conn) if conn else _needs_db(id_, name))
        findings.append(_safely(6, "scheduled task", check_scheduled_task, ctx))
        views_ok = next(f for f in findings if f.id == 4).status == PASS
        if conn is None:
            findings.append(_needs_db(7, "LCA data"))
        elif not views_ok:
            findings.append(Finding(7, "LCA data", SKIP, "needs the views (see check 4)"))
        else:
            findings.append(_safely(7, "LCA data", check_lca, ctx, conn))
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()
            conn.engine.dispose()
    findings.append(_safely(8, "file placement", check_file_placement, ctx))
    findings.append(_safely(9, "virtualenv", check_virtualenv, ctx))
    findings.append(_safely(10, "uv.lock", check_uv_lock, ctx))
    return findings


def _safely(id_: int, name: str, check: Callable[..., Finding], *args: Any) -> Finding:
    """A check that crashes is a FAIL with its error type, never a traceback."""
    try:
        return check(*args)
    except Exception as exc:
        if args and isinstance(args[-1], Connection):
            args[-1].rollback()
        return Finding(id_, name, FAIL, f"the check itself failed: {type(exc).__name__}")


def exit_code(findings: list[Finding]) -> int:
    return 1 if any(f.status == FAIL for f in findings) else 0


def format_findings(findings: list[Finding]) -> str:
    lines = ["Job Market Tracker doctor (read-only: it changes nothing)"]
    for f in findings:
        lines.append(f"  {f.status:<4} {f.id:>2} {f.name}: {f.detail}")
        if f.fix:
            lines.append(f"            fix:   {f.fix}")
        if f.fix_posix:
            lines.append(f"            posix: {f.fix_posix}")
    counts = {s: sum(f.status == s for f in findings) for s in (FAIL, WARN)}
    overall = FAIL if counts[FAIL] else WARN if counts[WARN] else PASS
    lines.append(
        f"overall {overall}: {counts[FAIL]} FAIL, {counts[WARN]} WARN; "
        f"exit code {exit_code(findings)}"
    )
    return "\n".join(lines)


def to_json(findings: list[Finding]) -> str:
    return json.dumps(
        {"exit_code": exit_code(findings), "checks": [asdict(f) for f in findings]}, indent=2
    )


def main() -> None:
    argp = argparse.ArgumentParser(
        description="Read-only check of this machine's setup, with the command to fix each problem."
    )
    argp.add_argument("--json", action="store_true", help="machine-readable output")
    args = argp.parse_args()
    findings = run_checks(Context())
    print(to_json(findings) if args.json else format_findings(findings))
    sys.exit(exit_code(findings))


if __name__ == "__main__":
    main()
