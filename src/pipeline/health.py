"""Is the daily clock actually running?

Run:  python -m src.pipeline.health [--json]      (or: make health)

Read-only: it never writes to the database. Each check is PASS, WARN or
FAIL with a one-line detail; exit code 1 if any check FAILs, else 0. The
daily runner calls it last. Thresholds are parked defaults, defined here
only (and documented in docs/data_dictionary.md):

  H1 run freshness (per source)  latest ok/partial run finished within
                                 RUN_FRESH_HOURS (26h), else FAIL. No run
                                 rows for the source at all -> WARN "no run
                                 log yet", with its latest jobs.last_seen_at.
  H2 snapshot freshness          latest snapshot_date is today (UTC) PASS,
                                 yesterday WARN, older or none FAIL.
  H3 snapshot volume (per source) WARN if the latest day's distinct jobs fell
                                 more than VOLUME_DROP (50%) against the
                                 previous snapshot day.
  H4 Adzuna budget               WARN at >= 85% of the month used, FAIL at
                                 >= 100% (src/ingestion/budget.py).
  H5 cleaning freshness          WARN if any job has no job_visa_signals
                                 row (cleaning hasn't run since ingestion).
  H6 failed runs                 WARN if any run in the last 7 days failed.

Progress lines are INFO and never fail: unique jobs vs 10,000, distinct
snapshot days vs 90, the current streak of consecutive snapshot days
ending today or yesterday vs 60, and the first snapshot date.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.ingestion.budget import adzuna_calls_used
from src.models import IngestionRun, Job, JobSnapshot, JobVisaSignal
from src.utils.config import get_settings
from src.utils.db import session_scope

SOURCES = ("adzuna", "usajobs")
RUN_FRESH_HOURS = 26
VOLUME_DROP = 0.50
BUDGET_WARN, BUDGET_FAIL = 0.85, 1.00
FAILED_LOOKBACK_DAYS = 7
TARGET_JOBS, TARGET_SNAPSHOT_DAYS, TARGET_STREAK_DAYS = 10_000, 90, 60

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


@dataclass
class Check:
    id: str
    name: str
    status: str
    detail: str


@dataclass
class HealthReport:
    now: datetime
    checks: list[Check] = field(default_factory=list)
    progress: list[Check] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if any(c.status == FAIL for c in self.checks) else 0

    @property
    def worst(self) -> str:
        statuses = {c.status for c in self.checks}
        return FAIL if FAIL in statuses else WARN if WARN in statuses else PASS

    def format(self) -> str:
        lines = [f"Ingestion health at {self.now.isoformat(timespec='minutes')} (UTC)"]
        lines += [f"  {c.status:<4} {c.id:<3} {c.name}: {c.detail}" for c in self.checks]
        lines += [f"  {c.status:<4} {c.name}: {c.detail}" for c in self.progress]
        lines.append(f"overall {self.worst}, exit code {self.exit_code}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "now": self.now.isoformat(),
                "overall": self.worst,
                "exit_code": self.exit_code,
                "checks": [asdict(c) for c in self.checks],
                "progress": [asdict(c) for c in self.progress],
            },
            indent=2,
        )


def _hours(delta: timedelta) -> str:
    return f"{delta.total_seconds() / 3600:.1f}h"


# --------------------------------------------------------------------- #
# checks


def check_run_freshness(session: Session, now: datetime, source: str) -> Check:
    name = f"run freshness ({source})"
    any_run = session.execute(
        select(func.count()).select_from(IngestionRun).where(IngestionRun.source == source)
    ).scalar_one()
    if not any_run:
        last_seen = session.execute(
            select(func.max(Job.last_seen_at)).where(Job.source == source)
        ).scalar_one()
        seen = last_seen.isoformat(timespec="minutes") if last_seen else "never"
        return Check("H1", name, WARN, f"no run log yet; latest jobs.last_seen_at {seen}")
    latest = session.execute(
        select(func.max(IngestionRun.finished_at)).where(
            IngestionRun.source == source, IngestionRun.status.in_(("ok", "partial"))
        )
    ).scalar_one()
    if latest is None:
        return Check("H1", name, FAIL, "run rows exist but none ended ok or partial")
    age = now - latest
    status = PASS if age <= timedelta(hours=RUN_FRESH_HOURS) else FAIL
    return Check(
        "H1", name, status, f"latest ok/partial run {_hours(age)} ago (limit {RUN_FRESH_HOURS}h)"
    )


def check_snapshot_freshness(session: Session, now: datetime) -> Check:
    latest = session.execute(select(func.max(JobSnapshot.snapshot_date))).scalar_one()
    today = now.date()
    if latest is None:
        return Check("H2", "snapshot freshness", FAIL, "no snapshots at all")
    if latest >= today:
        status, when = PASS, "today"
    elif latest == today - timedelta(days=1):
        status, when = WARN, "yesterday"
    else:
        status, when = FAIL, f"{(today - latest).days} days ago"
    return Check("H2", "snapshot freshness", status, f"latest snapshot_date {latest} ({when})")


def _daily_distinct_jobs(session: Session, source: str) -> list[tuple[date, int]]:
    rows = session.execute(
        select(JobSnapshot.snapshot_date, func.count(func.distinct(JobSnapshot.job_id)))
        .join(Job, Job.id == JobSnapshot.job_id)
        .where(Job.source == source)
        .group_by(JobSnapshot.snapshot_date)
        .order_by(JobSnapshot.snapshot_date.desc())
        .limit(2)
    ).all()
    return [(d, int(n)) for d, n in rows]


def check_snapshot_volume(session: Session, source: str) -> Check:
    name = f"snapshot volume ({source})"
    days = _daily_distinct_jobs(session, source)
    if len(days) < 2:
        return Check("H3", name, PASS, "fewer than two snapshot days; nothing to compare")
    (latest_day, latest_n), (prev_day, prev_n) = days
    drop = 1 - latest_n / prev_n if prev_n else 0.0
    status = WARN if drop > VOLUME_DROP else PASS
    return Check(
        "H3",
        name,
        status,
        f"{latest_n} jobs on {latest_day} vs {prev_n} on {prev_day} ({-drop:+.0%})",
    )


def check_budget(session: Session, now: datetime, budget: int) -> Check:
    used = adzuna_calls_used(session, now)
    share = used / budget if budget else 1.0
    status = FAIL if share >= BUDGET_FAIL else WARN if share >= BUDGET_WARN else PASS
    return Check("H4", "Adzuna budget", status, f"used {used} of {budget} this month ({share:.0%})")


def check_cleaning_freshness(session: Session) -> Check:
    missing = session.execute(
        select(func.count())
        .select_from(Job)
        .outerjoin(JobVisaSignal, JobVisaSignal.job_id == Job.id)
        .where(JobVisaSignal.job_id.is_(None))
    ).scalar_one()
    if missing:
        return Check(
            "H5",
            "cleaning freshness",
            WARN,
            f"{missing} job(s) have no job_visa_signals row; run apply_cleaning",
        )
    return Check("H5", "cleaning freshness", PASS, "every job has been through cleaning")


def check_failed_runs(session: Session, now: datetime) -> Check:
    since = now - timedelta(days=FAILED_LOOKBACK_DAYS)
    rows = session.execute(
        select(IngestionRun.source, func.count())
        .where(IngestionRun.status == "failed", IngestionRun.started_at >= since)
        .group_by(IngestionRun.source)
    ).all()
    if rows:
        detail = ", ".join(f"{source}: {n}" for source, n in sorted(rows))
        return Check(
            "H6",
            "failed runs",
            WARN,
            f"failed runs in the last {FAILED_LOOKBACK_DAYS} days: {detail}",
        )
    return Check("H6", "failed runs", PASS, f"none in the last {FAILED_LOOKBACK_DAYS} days")


# --------------------------------------------------------------------- #
# progress


def current_streak(days: list[date], today: date) -> int:
    """Consecutive snapshot days ending today or yesterday (0 if neither)."""
    present = set(days)
    start = today if today in present else today - timedelta(days=1)
    streak = 0
    while start - timedelta(days=streak) in present:
        streak += 1
    return streak


def progress(session: Session, now: datetime) -> list[Check]:
    unique_jobs = session.execute(select(func.count()).select_from(Job)).scalar_one()
    days = list(session.execute(select(JobSnapshot.snapshot_date).distinct()).scalars())
    streak = current_streak(days, now.date())
    first = min(days).isoformat() if days else "none yet"
    return [
        Check("P1", "unique jobs", INFO, f"{unique_jobs:,} of {TARGET_JOBS:,}"),
        Check("P2", "snapshot days", INFO, f"{len(days)} of {TARGET_SNAPSHOT_DAYS}"),
        Check("P3", "current streak", INFO, f"{streak} of {TARGET_STREAK_DAYS} consecutive days"),
        Check("P4", "first snapshot", INFO, first),
    ]


def run_health(session: Session, now: datetime, budget: int) -> HealthReport:
    report = HealthReport(now=now)
    report.checks += [check_run_freshness(session, now, s) for s in SOURCES]
    report.checks.append(check_snapshot_freshness(session, now))
    report.checks += [check_snapshot_volume(session, s) for s in SOURCES]
    report.checks.append(check_budget(session, now, budget))
    report.checks.append(check_cleaning_freshness(session))
    report.checks.append(check_failed_runs(session, now))
    report.progress = progress(session, now)
    return report


def health(
    database_url: str | None = None, now: datetime | None = None, budget: int | None = None
) -> HealthReport:
    if budget is None:
        budget = get_settings().adzuna_monthly_call_budget
    with session_scope(database_url) as session:
        report = run_health(session, now or datetime.now(UTC), budget)
        session.rollback()  # read-only: never commit anything
    return report


def main() -> None:
    argp = argparse.ArgumentParser(description="Is the daily ingestion clock running?")
    argp.add_argument("--json", action="store_true", help="machine-readable output")
    args = argp.parse_args()
    report = health()
    print(report.to_json() if args.json else report.format())
    sys.exit(report.exit_code)


if __name__ == "__main__":
    main()
