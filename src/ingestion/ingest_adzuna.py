"""Adzuna ingestion pipeline.

Run:  python -m src.ingestion.ingest_adzuna [--dry-run] [--max-pages N] ...

For each target query:
  1. Fetch a page of results.
  2. Persist the raw response verbatim -> raw_responses  (the insurance policy)
  3. For each job:
     a. Upsert company by exact display_name        -> companies
     b. Upsert location by (city, state, country)   -> locations
     c. Upsert job by (source, external_id)         -> jobs
        - INSERT if new; on conflict, refresh last_seen_at + mutable fields
     d. Upsert today's snapshot                     -> job_snapshots

Idempotency: re-running the sync never creates duplicates and always
brings the dataset to the latest observed state. Verified by
tests/test_ingestion.py against a real Postgres.
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.ingestion import adzuna_parser as parser
from src.ingestion.adzuna_client import AdzunaClient, CallBudgetExceeded
from src.ingestion.budget import BudgetDecision, plan_adzuna_run
from src.ingestion.run_log import RunStats, record_terminal_run, recorded_run
from src.models import Company, Job, JobSnapshot, Location, RawResponse
from src.utils.config import Settings, get_settings
from src.utils.db import session_scope
from src.utils.redaction import install_redaction, secrets_from_settings

logger = logging.getLogger(__name__)

TARGET_QUERIES = [
    "data analyst",
    "senior data analyst",
    "analytics engineer",
    "business intelligence analyst",
    "marketing analyst",
    "product analyst",
]

# Fields refreshed when a known job is seen again. Salary and description
# can genuinely change on a live posting; identity fields never do.
JOB_UPDATE_FIELDS = [
    "title",
    "title_normalized",
    "description",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "salary_is_predicted",
    "is_remote",
    "category",
    "contract_type",
    "contract_time",
    "redirect_url",
]


# --------------------------------------------------------------------- #
# persistence helpers (each takes an open session; commits happen at the
# page level so a mid-page crash never leaves a half-parsed raw response)


def save_raw_response(session: Session, endpoint: str, params: dict, response: dict) -> int:
    row = RawResponse(source=parser.SOURCE, endpoint=endpoint, params=params, response=response)
    session.add(row)
    session.flush()
    return row.id


def upsert_company(session: Session, fields: dict | None) -> int | None:
    if fields is None:
        return None
    stmt = (
        pg_insert(Company)
        .values(**fields)
        .on_conflict_do_update(
            index_elements=[Company.canonical_name],
            set_={"canonical_name": fields["canonical_name"]},  # no-op update to get RETURNING
        )
        .returning(Company.id)
    )
    return session.execute(stmt).scalar_one()


def upsert_location(session: Session, fields: dict | None) -> int | None:
    if fields is None:
        return None
    key = {
        "city": fields.get("city"),
        "state": fields.get("state"),
        "country": fields.get("country"),
    }
    # Postgres unique constraints treat NULLs as distinct, so ON CONFLICT
    # can't dedupe rows like (NULL, 'Virginia', 'US'). Select-then-insert
    # instead; safe here because ingestion is single-writer.
    existing = session.execute(
        select(Location.id).where(
            *(
                Location.__table__.c[col].is_(None)
                if val is None
                else Location.__table__.c[col] == val
                for col, val in key.items()
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = Location(**fields)
    session.add(row)
    session.flush()
    return row.id


def upsert_job(
    session: Session,
    fields: dict,
    company_id: int | None,
    location_id: int | None,
    raw_response_id: int,
    seen_at: datetime,
) -> int:
    values = {
        **fields,
        "company_id": company_id,
        "location_id": location_id,
        "raw_response_id": raw_response_id,
        "first_seen_at": seen_at,
        "last_seen_at": seen_at,
    }
    stmt = (
        pg_insert(Job)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_jobs_source_external_id",
            set_={
                **{f: values[f] for f in JOB_UPDATE_FIELDS},
                "last_seen_at": seen_at,
                "removed_at": None,  # job is visibly back if it was marked removed
            },
        )
        .returning(Job.id)
    )
    return session.execute(stmt).scalar_one()


def upsert_snapshot(session: Session, job_id: int, fields: dict, snapshot_date: date) -> None:
    stmt = (
        pg_insert(JobSnapshot)
        .values(
            job_id=job_id,
            snapshot_date=snapshot_date,
            is_active=True,
            salary_min=fields.get("salary_min"),
            salary_max=fields.get("salary_max"),
        )
        .on_conflict_do_update(
            index_elements=[JobSnapshot.job_id, JobSnapshot.snapshot_date],
            set_={
                "is_active": True,
                "salary_min": fields.get("salary_min"),
                "salary_max": fields.get("salary_max"),
            },
        )
    )
    session.execute(stmt)


# --------------------------------------------------------------------- #


def ingest_page(session: Session, query: str, page: int, response: dict) -> int:
    """Persist one raw page + all its jobs. Returns jobs processed."""
    now = datetime.now(UTC)
    today = now.date()
    raw_id = save_raw_response(
        session,
        endpoint=f"/jobs/us/search/{page}",
        params={"what": query, "page": page},
        response=response,
    )
    processed = 0
    for raw_job in response.get("results", []):
        try:
            job_fields = parser.parse_job(raw_job)
        except KeyError:
            logger.warning("Skipping result with no id in query %r page %d", query, page)
            continue
        company_id = upsert_company(session, parser.parse_company(raw_job))
        location_id = upsert_location(session, parser.parse_location(raw_job))
        job_id = upsert_job(session, job_fields, company_id, location_id, raw_id, now)
        upsert_snapshot(session, job_id, job_fields, today)
        processed += 1
    return processed


def run_ingestion(
    client: AdzunaClient,
    queries: list[str] | None = None,
    max_pages_per_query: int = 5,
    results_per_page: int = 50,
    dry_run: bool = False,
    database_url: str | None = None,
    stats: RunStats | None = None,
) -> dict[str, int]:
    """Full ingestion across all target queries. Returns per-query counts."""
    queries = queries or TARGET_QUERIES
    counts: dict[str, int] = {}
    for query in queries:
        counts[query] = 0
        try:
            for page, response in client.iter_search(
                query,
                max_results=max_pages_per_query * results_per_page,
                results_per_page=results_per_page,
            ):
                if dry_run:
                    n = len(response.get("results", []))
                    logger.info("[dry-run] %r page %d: %d results (not persisted)", query, page, n)
                    counts[query] += n
                    continue
                with session_scope(database_url) as session:
                    n = ingest_page(session, query, page, response)
                counts[query] += n
                if stats is not None:
                    stats.pages_fetched += 1
                    stats.jobs_processed += n
        except CallBudgetExceeded as exc:
            logger.error("Stopping: %s", exc)
            if stats is not None:
                stats.budget_cut = True
            break
    return counts


def build_client(settings: Settings, max_calls: int) -> AdzunaClient:
    """An AdzunaClient from Settings (raises AdzunaError if credentials are empty)."""
    return AdzunaClient(
        app_id=settings.adzuna_app_id,
        app_key=settings.adzuna_app_key,
        min_request_interval=settings.adzuna_min_request_interval,
        max_calls=max_calls,
    )


def run_logged(
    client: AdzunaClient,
    queries: list[str] | None = None,
    max_pages_per_query: int = 5,
    database_url: str | None = None,
    extra_params: dict | None = None,
) -> tuple[dict[str, int], RunStats]:
    """run_ingestion wrapped in an ingestion_runs row (see run_log.py).
    Re-raises after recording a failure."""
    params = {
        "queries": queries or TARGET_QUERIES,
        "max_pages": max_pages_per_query,
        "max_calls": client.max_calls,
        "dry_run": False,
        **(extra_params or {}),
    }
    with recorded_run(
        parser.SOURCE,
        params,
        client=client,
        secrets=client.credential_values(),
        database_url=database_url,
    ) as stats:
        counts = run_ingestion(
            client,
            queries=queries,
            max_pages_per_query=max_pages_per_query,
            database_url=database_url,
            stats=stats,
        )
    return counts, stats


def plan_budget(
    settings: Settings, max_calls: int, database_url: str | None = None, now: datetime | None = None
) -> BudgetDecision:
    with session_scope(database_url) as session:
        decision = plan_adzuna_run(
            session,
            now or datetime.now(UTC),
            max_calls=max_calls,
            budget=settings.adzuna_monthly_call_budget,
            reserve=settings.adzuna_monthly_reserve,
        )
    logger.info("Adzuna budget: %s", decision.describe())
    return decision


def run_guarded(
    settings: Settings,
    max_calls: int,
    queries: list[str] | None = None,
    max_pages_per_query: int = 5,
    database_url: str | None = None,
    now: datetime | None = None,
    client_factory=None,
) -> tuple[str, dict[str, int], BudgetDecision]:
    """Budget-guarded, run-logged Adzuna ingestion (src/ingestion/budget.py).

    Returns (status, counts, decision). When the monthly cap for this run
    is <= 0, no client is built and no call is made: a `skipped_budget`
    run is recorded and a warning logged. Exceptions from the run itself
    are recorded as `failed` and re-raised.
    """
    decision = plan_budget(settings, max_calls, database_url, now)
    params = {
        "queries": queries or TARGET_QUERIES,
        "max_pages": max_pages_per_query,
        "max_calls": decision.cap,
        "requested_max_calls": max_calls,
        "dry_run": False,
    }
    if decision.skip:
        logger.warning("Skipping Adzuna run: monthly budget exhausted (%s)", decision.describe())
        record_terminal_run(
            parser.SOURCE,
            "skipped_budget",
            params,
            f"skipped: {decision.describe()}",
            database_url=database_url,
        )
        return "skipped_budget", {}, decision
    client = (client_factory or build_client)(settings, decision.cap)
    counts, stats = run_logged(
        client,
        queries=queries,
        max_pages_per_query=max_pages_per_query,
        database_url=database_url,
        extra_params={"requested_max_calls": max_calls},
    )
    logger.info("API calls used this run: %d / %d", client.calls_made, decision.cap)
    return ("partial" if stats.budget_cut else "ok"), counts, decision


def summarize(database_url: str | None = None) -> None:
    with session_scope(database_url) as session:
        jobs = session.execute(select(func.count()).select_from(Job)).scalar_one()
        companies = session.execute(select(func.count()).select_from(Company)).scalar_one()
        locations = session.execute(select(func.count()).select_from(Location)).scalar_one()
        raw = session.execute(select(func.count()).select_from(RawResponse)).scalar_one()
        snaps = session.execute(select(func.count()).select_from(JobSnapshot)).scalar_one()
    logger.info(
        "DB totals — jobs: %d | companies: %d | locations: %d | raw_responses: %d | snapshots: %d",
        jobs,
        companies,
        locations,
        raw,
        snaps,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    argp = argparse.ArgumentParser(description="Ingest Adzuna job postings.")
    argp.add_argument("--queries", nargs="*", default=None, help="Override target queries")
    argp.add_argument("--max-pages", type=int, default=5, help="Max pages per query (default 5)")
    argp.add_argument(
        "--max-calls",
        type=int,
        default=60,
        help="Hard API call budget for this run (default 60; free tier is 1000/month)",
    )
    argp.add_argument(
        "--dry-run", action="store_true", help="Fetch but do not write to the database"
    )
    args = argp.parse_args()

    settings = get_settings(require_adzuna=True)
    install_redaction(secrets_from_settings(settings))
    if args.dry_run:
        # A dry run still spends real API calls (it only skips the writes),
        # so it is capped by the monthly budget too -- but records no run row.
        decision = plan_budget(settings, args.max_calls)
        if decision.skip:
            logger.warning("Skipping dry run: monthly budget exhausted")
            return
        client = build_client(settings, decision.cap)
        counts = run_ingestion(
            client, queries=args.queries, max_pages_per_query=args.max_pages, dry_run=True
        )
        logger.info("API calls used this run: %d / %d", client.calls_made, decision.cap)
    else:
        status, counts, _ = run_guarded(
            settings, args.max_calls, queries=args.queries, max_pages_per_query=args.max_pages
        )
        if status == "skipped_budget":
            return
    for query, n in counts.items():
        logger.info("Query %r: %d jobs processed", query, n)
    if not args.dry_run:
        summarize()


if __name__ == "__main__":
    main()
