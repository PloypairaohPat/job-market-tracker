"""Run log: one `ingestion_runs` row per ingestion run, always closed.

Both ingestion paths (ingest_adzuna, ingest_usajobs) and the daily runner
go through `recorded_run`:

    with recorded_run("adzuna", params, client=client, secrets=...) as stats:
        run_ingestion(client, ..., stats=stats)

- On entry a row is committed as `running` (so a crashed or killed run
  stays visible as running with no finished_at).
- On a clean exit it closes as `ok`, or `partial` when the per-run call
  budget cut the run short (`stats.budget_cut`, set by run_ingestion).
- On any exception it closes as `failed` with the redacted, truncated
  error text, then re-raises -- callers decide whether to continue.

`jobs_new` = jobs for the source after the run minus before it (ingestion
is single-writer, so the difference is this run's inserts). `calls_made`
is read from the client, which counts every HTTP attempt, retries
included -- the right number to bill against the monthly budget.

Dry runs never come through here: they write nothing, run row included.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from src.models import IngestionRun, Job
from src.utils.db import session_scope
from src.utils.redaction import redact

ERROR_MAX_CHARS = 2000


@dataclass
class RunStats:
    """Filled in by run_ingestion(..., stats=) while the run progresses."""

    pages_fetched: int = 0
    jobs_processed: int = 0
    budget_cut: bool = False  # the per-run call budget stopped the run early


def safe_error(exc: BaseException | str, secrets: Iterable[str] = ()) -> str:
    text = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    return redact(text, secrets)[:ERROR_MAX_CHARS]


def _job_count(session, source: str) -> int:
    return session.execute(
        select(func.count()).select_from(Job).where(Job.source == source)
    ).scalar_one()


def record_terminal_run(
    source: str,
    status: str,
    params: dict[str, Any],
    error: str | None = None,
    *,
    secrets: Iterable[str] = (),
    database_url: str | None = None,
    now: datetime | None = None,
) -> int:
    """Write a run that never started fetching: `skipped_budget`, or `failed`
    before a client existed (e.g. missing credentials). Returns its id."""
    now = now or datetime.now(UTC)
    with session_scope(database_url) as session:
        run = IngestionRun(
            source=source,
            started_at=now,
            finished_at=now,
            status=status,
            snapshot_date=now.date(),
            params=params,
            error=safe_error(error, secrets) if error else None,
        )
        session.add(run)
        session.flush()
        return run.id


@contextmanager
def recorded_run(
    source: str,
    params: dict[str, Any],
    *,
    client: Any = None,
    secrets: Iterable[str] = (),
    database_url: str | None = None,
) -> Iterator[RunStats]:
    secrets = list(secrets)
    started = datetime.now(UTC)
    with session_scope(database_url) as session:
        jobs_before = _job_count(session, source)
        run = IngestionRun(
            source=source,
            started_at=started,
            status="running",
            snapshot_date=started.date(),
            params=params,
        )
        session.add(run)
        session.flush()
        run_id = run.id

    stats = RunStats()
    status, error = "ok", None
    try:
        yield stats
        status = "partial" if stats.budget_cut else "ok"
    except BaseException as exc:
        status, error = "failed", safe_error(exc, secrets)
        raise
    finally:
        with session_scope(database_url) as session:
            run = session.get(IngestionRun, run_id)
            run.finished_at = datetime.now(UTC)
            run.status = status
            run.error = error
            run.calls_made = getattr(client, "calls_made", 0) or 0
            run.pages_fetched = stats.pages_fetched
            run.jobs_processed = stats.jobs_processed
            run.jobs_new = max(0, _job_count(session, source) - jobs_before)
