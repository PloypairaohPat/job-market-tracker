"""Monthly Adzuna call budget.

Adzuna's free tier is 1,000 calls a month. The per-run `--max-calls` cap
alone can't enforce that: thirty-one 30-call runs plus a few manual runs
overshoot. Before every Adzuna run:

    used = max(sum(ingestion_runs.calls_made) for adzuna this UTC month,
               count(raw_responses) for adzuna fetched this UTC month)
    cap  = min(max_calls, (budget - used - reserve) // days_left)

- The billing month is the UTC calendar month (parked: Adzuna may count
  from the signup date).
- `ingestion_runs.calls_made` counts every HTTP attempt, retries and
  failures included. `raw_responses` only holds successful pages, so it
  undercounts, but it is the only record from before the run log existed;
  taking the larger of the two covers both.
- `reserve` (ADZUNA_MONTHLY_RESERVE, default 25) is held back for manual
  and smoke-test calls.
- Dividing the remainder by the days left in the month (today included)
  guarantees later days still get calls. Day 1 with nothing used:
  (1000 - 0 - 25) // 31 = 31 >= 30, so a normal 30-call run is never
  throttled.
- cap <= 0 means skip: no client is built and no call is made; the caller
  records a `skipped_budget` run. That is not an error.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import IngestionRun, RawResponse

SOURCE = "adzuna"


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """[start, end) of the UTC calendar month containing `now`."""
    now = now.astimezone(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def days_left_in_month(now: datetime) -> int:
    """Days remaining in the UTC month, today included (31 on Oct 1, 1 on Oct 31)."""
    now = now.astimezone(UTC)
    return calendar.monthrange(now.year, now.month)[1] - now.day + 1


def adzuna_calls_used(session: Session, now: datetime) -> int:
    start, end = month_bounds(now)
    from_runs = session.execute(
        select(func.coalesce(func.sum(IngestionRun.calls_made), 0)).where(
            IngestionRun.source == SOURCE,
            IngestionRun.started_at >= start,
            IngestionRun.started_at < end,
        )
    ).scalar_one()
    from_raw = session.execute(
        select(func.count())
        .select_from(RawResponse)
        .where(
            RawResponse.source == SOURCE,
            RawResponse.fetched_at >= start,
            RawResponse.fetched_at < end,
        )
    ).scalar_one()
    return max(int(from_runs), int(from_raw))


@dataclass(frozen=True)
class BudgetDecision:
    used: int
    budget: int
    reserve: int
    days_left: int
    max_calls: int
    cap: int

    @property
    def skip(self) -> bool:
        return self.cap <= 0

    def describe(self) -> str:
        return (
            f"used {self.used} of {self.budget} this month, cap for this run {self.cap} "
            f"(reserve {self.reserve}, {self.days_left} day(s) left incl. today, "
            f"--max-calls {self.max_calls})"
        )


def plan_adzuna_run(
    session: Session, now: datetime, max_calls: int, budget: int, reserve: int
) -> BudgetDecision:
    used = adzuna_calls_used(session, now)
    days_left = days_left_in_month(now)
    cap = min(max_calls, (budget - used - reserve) // days_left)
    return BudgetDecision(
        used=used,
        budget=budget,
        reserve=reserve,
        days_left=days_left,
        max_calls=max_calls,
        cap=cap,
    )
