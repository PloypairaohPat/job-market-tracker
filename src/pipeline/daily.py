"""The daily pipeline: both sources, then cleaning, then skills.

Run:  python -m src.pipeline.daily [--skip adzuna usajobs cleaning skills] [--dry-run]
      (or: make daily; on Windows the scheduled task runs scripts/windows/run_daily.ps1)

Steps, in order, called in-process (so tests inject fixture-backed clients):
  1. adzuna    budget-guarded (src/ingestion/budget.py), run-logged
  2. usajobs   run-logged, keyword queries + TARGET_SERIES_CODES
  3. cleaning  every apply_cleaning step (ALL_STEPS)
  4. skills    sync_taxonomy + extract_for_all_jobs
  5. health    src/pipeline/health.py (read-only); fails the run on any FAIL

Judgment calls (docs/daily-operation.md, docs/data_dictionary.md):
- One source failing (missing credentials, API error) is recorded as a
  `failed` ingestion_runs row and the run continues. Cleaning and skills
  still run: they only read the database and are idempotent.
- Missing credentials: the error names the missing variable, never a value.
- Single instance via a Postgres advisory lock (`pg_try_advisory_lock`,
  key DAILY_LOCK_KEY) held on a dedicated connection for the whole run. A
  second runner logs that and exits 0. No file locks, so Windows and
  POSIX behave the same.
- Logs go to stdout and logs/daily-YYYY-MM-DD.log (UTC date, UTF-8,
  appended), through the secret-redaction filter. No rotation.
- Exit 0 when every step that ran succeeded (`skipped_budget` and
  `partial` count as success: the guard did its job); 1 otherwise.
- `--dry-run` is a PLAN only: it logs the budget decision and the steps
  that would run, and makes no API call and no write. (The ingest CLIs'
  --dry-run fetches without writing; here that would spend budget the
  run log can't see.)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from src.cleaning.apply_cleaning import ALL_STEPS, DEFAULT_CANDIDATES_OUT, run_steps
from src.cleaning.extract_skills import extract_for_all_jobs, sync_taxonomy
from src.ingestion import ingest_adzuna, ingest_usajobs
from src.ingestion.run_log import record_terminal_run
from src.pipeline.health import FAIL, health
from src.utils.config import Settings, get_settings
from src.utils.db import session_scope
from src.utils.redaction import install_redaction, secrets_from_settings

logger = logging.getLogger("src.pipeline.daily")

# pg_try_advisory_lock key for "one daily run at a time". Any bigint works;
# this one spells "JMTD" (Job Market Tracker Daily) in ASCII.
DAILY_LOCK_KEY = 0x4A4D5444

STEPS = ("adzuna", "usajobs", "cleaning", "skills", "health")
SOURCE_MAX_CALLS = 60  # per-run cap, same default as the ingest CLIs
LOG_DIR = Path("logs")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@dataclass
class StepResult:
    name: str
    ok: bool
    status: str  # ok | partial | skipped_budget | failed | skipped | planned
    seconds: float = 0.0
    detail: str = ""


@dataclass
class DailyResult:
    exit_code: int
    steps: list[StepResult] = field(default_factory=list)
    locked_out: bool = False


# --------------------------------------------------------------------- #
# logging


@contextmanager
def daily_logging(log_dir: Path, secrets: list[str], now: datetime) -> Iterator[Path]:
    """stdout + logs/daily-<UTC date>.log on the root logger, redacted.
    Handlers are removed on exit so repeated in-process runs don't stack."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"daily-{now.astimezone(UTC).date().isoformat()}.log"
    formatter = logging.Formatter(LOG_FORMAT)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(path, mode="a", encoding="utf-8"),
    ]
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    install_redaction(secrets, handlers=handlers)
    try:
        yield path
    finally:
        for handler in handlers:
            root.removeHandler(handler)
            handler.close()
        root.setLevel(old_level)


# --------------------------------------------------------------------- #
# single-instance lock


@contextmanager
def advisory_lock(database_url: str) -> Iterator[bool]:
    """Yield True if this process now holds DAILY_LOCK_KEY, else False."""
    engine = create_engine(database_url)
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        got = conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": DAILY_LOCK_KEY}).scalar()
        try:
            yield bool(got)
        finally:
            if got:
                conn.execute(text("select pg_advisory_unlock(:k)"), {"k": DAILY_LOCK_KEY})
    finally:
        conn.close()
        engine.dispose()


# --------------------------------------------------------------------- #
# steps


def _missing(settings: Settings, names: dict[str, str]) -> list[str]:
    return [env for env, attr in names.items() if not getattr(settings, attr)]


def step_adzuna(ctx: dict) -> StepResult:
    settings: Settings = ctx["settings"]
    missing = _missing(
        settings, {"ADZUNA_APP_ID": "adzuna_app_id", "ADZUNA_APP_KEY": "adzuna_app_key"}
    )
    if missing:
        error = f"Missing required environment variable(s): {', '.join(missing)}"
        record_terminal_run("adzuna", "failed", {}, error, database_url=ctx["database_url"])
        return StepResult("adzuna", False, "failed", detail=error)
    if ctx["dry_run"]:
        decision = ingest_adzuna.plan_budget(
            settings, SOURCE_MAX_CALLS, ctx["database_url"], ctx["now"]
        )
        return StepResult("adzuna", True, "planned", detail=decision.describe())
    status, counts, decision = ingest_adzuna.run_guarded(
        settings,
        SOURCE_MAX_CALLS,
        database_url=ctx["database_url"],
        now=ctx["now"],
        client_factory=ctx["adzuna_client_factory"],
    )
    return StepResult(
        "adzuna",
        True,
        status,
        detail=f"jobs processed {sum(counts.values())}; {decision.describe()}",
    )


def step_usajobs(ctx: dict) -> StepResult:
    settings: Settings = ctx["settings"]
    missing = _missing(
        settings,
        {
            "USAJOBS_API_KEY": "usajobs_api_key",
            "USAJOBS_USER_AGENT_EMAIL": "usajobs_user_agent_email",
        },
    )
    if missing:
        error = f"Missing required environment variable(s): {', '.join(missing)}"
        record_terminal_run("usajobs", "failed", {}, error, database_url=ctx["database_url"])
        return StepResult("usajobs", False, "failed", detail=error)
    if ctx["dry_run"]:
        return StepResult("usajobs", True, "planned", detail="would run keyword + series searches")
    client = ctx["usajobs_client_factory"](settings, SOURCE_MAX_CALLS)
    counts, stats = ingest_usajobs.run_logged(
        client,
        series_codes=ingest_usajobs.TARGET_SERIES_CODES,
        database_url=ctx["database_url"],
    )
    status = "partial" if stats.budget_cut else "ok"
    return StepResult(
        "usajobs",
        True,
        status,
        detail=f"jobs processed {stats.jobs_processed}; calls {client.calls_made}",
    )


def step_cleaning(ctx: dict) -> StepResult:
    if ctx["dry_run"]:
        return StepResult("cleaning", True, "planned", detail=f"would run {', '.join(ALL_STEPS)}")
    with session_scope(ctx["database_url"]) as session:
        results = run_steps(session, ALL_STEPS, ctx["candidates_out"])
    return StepResult("cleaning", True, "ok", detail=f"ran {', '.join(results)}")


def step_skills(ctx: dict) -> StepResult:
    if ctx["dry_run"]:
        return StepResult("skills", True, "planned", detail="would sync taxonomy + extract")
    with session_scope(ctx["database_url"]) as session:
        skill_ids = sync_taxonomy(session)
        jobs, links = extract_for_all_jobs(session, skill_ids)
    return StepResult(
        "skills", True, "ok", detail=f"{len(skill_ids)} skills; {jobs} jobs; {links} links"
    )


def step_health(ctx: dict) -> StepResult:
    report = health(ctx["database_url"], ctx["now"], ctx["settings"].adzuna_monthly_call_budget)
    logger.info("health:\n%s", report.format())
    problems = [f"{c.id} {c.status}" for c in report.checks if c.status != "PASS"]
    detail = f"overall {report.worst}" + (f" ({', '.join(problems)})" if problems else "")
    ok = not any(c.status == FAIL for c in report.checks)
    return StepResult("health", ok, report.worst.lower(), detail=detail)


STEP_FUNCS: dict[str, Callable[[dict], StepResult]] = {
    "adzuna": step_adzuna,
    "usajobs": step_usajobs,
    "cleaning": step_cleaning,
    "skills": step_skills,
    "health": step_health,
}


def _run_step(name: str, ctx: dict) -> StepResult:
    logger.info("step %s: start", name)
    started = time.monotonic()
    try:
        result = STEP_FUNCS[name](ctx)
    except Exception as exc:  # recorded, and the run continues
        logger.exception("step %s: failed", name)
        result = StepResult(name, False, "failed", detail=f"{type(exc).__name__}: {exc}")
    result.seconds = time.monotonic() - started
    logger.info(
        "step %s: end status=%s in %.1fs -- %s", name, result.status, result.seconds, result.detail
    )
    return result


# --------------------------------------------------------------------- #


def format_summary(result: DailyResult) -> str:
    lines = ["", "=" * 72, "Daily run summary"]
    for s in result.steps:
        mark = "OK  " if s.ok else "FAIL"
        lines.append(f"  {mark} {s.name:<9} {s.status:<15} {s.seconds:6.1f}s  {s.detail}")
    lines.append(f"exit code {result.exit_code}")
    lines.append("=" * 72)
    return "\n".join(lines)


def run_daily(
    skip: tuple[str, ...] = (),
    dry_run: bool = False,
    *,
    settings: Settings | None = None,
    database_url: str | None = None,
    now: datetime | None = None,
    log_dir: Path = LOG_DIR,
    candidates_out: Path = DEFAULT_CANDIDATES_OUT,
    adzuna_client_factory=None,
    usajobs_client_factory=None,
) -> DailyResult:
    settings = settings or get_settings()
    database_url = database_url or settings.database_url
    now = now or datetime.now(UTC)
    ctx = {
        "settings": settings,
        "database_url": database_url,
        "now": now,
        "dry_run": dry_run,
        "candidates_out": candidates_out,
        "adzuna_client_factory": adzuna_client_factory or ingest_adzuna.build_client,
        "usajobs_client_factory": usajobs_client_factory or ingest_usajobs.build_client,
    }
    with daily_logging(log_dir, secrets_from_settings(settings), now) as log_path:
        logger.info("daily run starting (UTC date %s), log %s", now.date().isoformat(), log_path)
        with advisory_lock(database_url) as locked:
            if not locked:
                logger.warning(
                    "another daily run holds advisory lock %d; exiting without doing anything",
                    DAILY_LOCK_KEY,
                )
                return DailyResult(exit_code=0, locked_out=True)
            result = DailyResult(exit_code=0)
            for name in STEPS:
                if name in skip:
                    result.steps.append(StepResult(name, True, "skipped", detail="--skip"))
                    continue
                result.steps.append(_run_step(name, ctx))
        result.exit_code = 0 if all(s.ok for s in result.steps) else 1
        logger.info(format_summary(result))
        return result


def main() -> None:
    argp = argparse.ArgumentParser(description="Run the daily ingestion pipeline.")
    argp.add_argument("--skip", nargs="*", choices=STEPS, default=[], help="steps to skip")
    argp.add_argument(
        "--dry-run",
        action="store_true",
        help="plan only: log the budget decision and steps; no API calls, no writes",
    )
    args = argp.parse_args()
    result = run_daily(skip=tuple(args.skip), dry_run=args.dry_run)
    sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
