"""USAJobs ingestion pipeline.

Run:  python -m src.ingestion.ingest_usajobs [--dry-run] [--max-pages N] ...

Mirrors `ingest_adzuna.py` exactly:
  1. Fetch a page of results.
  2. Persist the raw response verbatim -> raw_responses  (source='usajobs')
  3. For each job:
     a. Upsert company by DepartmentName             -> companies
     b. Upsert location by (city, state, country)    -> locations
     c. Upsert job by (source, external_id)          -> jobs
     d. Upsert today's snapshot                      -> job_snapshots

Idempotency: re-running the sync never creates duplicates and always
brings the dataset to the latest observed state.

`upsert_company`, `upsert_location`, and `upsert_snapshot` are reused
from `ingest_adzuna` as-is -- they only ever touch their `fields`
argument, so they're genuinely source-agnostic. `save_raw_response` and
`upsert_job` are defined locally instead: `ingest_adzuna`'s versions
close over that module's own `parser.SOURCE` / `JOB_UPDATE_FIELDS`
globals rather than taking them as arguments, so reusing them as-is
would silently tag every raw response `source='adzuna'` and never
refresh `description_full` on re-observation.
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.ingestion import usajobs_parser as parser
from src.ingestion.ingest_adzuna import upsert_company, upsert_location, upsert_snapshot
from src.ingestion.usajobs_client import CallBudgetExceeded, USAJobsClient
from src.models import Company, Job, JobSnapshot, Location, RawResponse
from src.utils.config import get_settings
from src.utils.db import session_scope

logger = logging.getLogger(__name__)

TARGET_QUERIES = [
    "data analyst",
    "senior data analyst",
    "analytics engineer",
    "business intelligence analyst",
    "marketing analyst",
    "product analyst",
]

# Fields refreshed when a known job is seen again. description_full can
# genuinely change (an agency edits the announcement); identity fields
# never do.
JOB_UPDATE_FIELDS = [
    "title",
    "title_normalized",
    "description",
    "description_full",
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


def save_raw_response(session: Session, endpoint: str, params: dict, response: dict) -> int:
    row = RawResponse(source=parser.SOURCE, endpoint=endpoint, params=params, response=response)
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
                "removed_at": None,
            },
        )
        .returning(Job.id)
    )
    return session.execute(stmt).scalar_one()


# --------------------------------------------------------------------- #


def ingest_page(session: Session, query: str, page: int, response: dict) -> int:
    """Persist one raw page + all its jobs. Returns jobs processed."""
    now = datetime.now(UTC)
    today = now.date()
    items = response.get("SearchResult", {}).get("SearchResultItems", [])
    raw_id = save_raw_response(
        session,
        endpoint="/api/search",
        params={"Keyword": query, "Page": page},
        response=response,
    )
    processed = 0
    for raw_job in items:
        try:
            job_fields = parser.parse_job(raw_job)
        except KeyError:
            logger.warning("Skipping result with no MatchedObjectId in query %r page %d", query, page)
            continue
        company_id = upsert_company(session, parser.parse_company(raw_job))
        location_id = upsert_location(session, parser.parse_location(raw_job))
        job_id = upsert_job(session, job_fields, company_id, location_id, raw_id, now)
        upsert_snapshot(session, job_id, job_fields, today)
        processed += 1
    return processed


def run_ingestion(
    client: USAJobsClient,
    queries: list[str] | None = None,
    max_pages_per_query: int = 5,
    results_per_page: int = 25,
    dry_run: bool = False,
    database_url: str | None = None,
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
                    n = len(response.get("SearchResult", {}).get("SearchResultItems", []))
                    logger.info("[dry-run] %r page %d: %d results (not persisted)", query, page, n)
                    counts[query] += n
                    continue
                with session_scope(database_url) as session:
                    counts[query] += ingest_page(session, query, page, response)
        except CallBudgetExceeded as exc:
            logger.error("Stopping: %s", exc)
            break
    return counts


def summarize(database_url: str | None = None) -> None:
    with session_scope(database_url) as session:
        jobs = session.execute(
            select(func.count()).select_from(Job).where(Job.source == "usajobs")
        ).scalar_one()
        companies = session.execute(select(func.count()).select_from(Company)).scalar_one()
        locations = session.execute(select(func.count()).select_from(Location)).scalar_one()
        raw = session.execute(
            select(func.count()).select_from(RawResponse).where(RawResponse.source == "usajobs")
        ).scalar_one()
        snaps = session.execute(select(func.count()).select_from(JobSnapshot)).scalar_one()
    logger.info(
        "DB totals (usajobs) — jobs: %d | companies (all sources): %d | "
        "locations (all sources): %d | raw_responses: %d | snapshots (all sources): %d",
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
    argp = argparse.ArgumentParser(description="Ingest USAJobs job postings.")
    argp.add_argument("--queries", nargs="*", default=None, help="Override target queries")
    argp.add_argument("--max-pages", type=int, default=5, help="Max pages per query (default 5)")
    argp.add_argument(
        "--max-calls",
        type=int,
        default=60,
        help="Hard API call budget for this run (default 60)",
    )
    argp.add_argument(
        "--dry-run", action="store_true", help="Fetch but do not write to the database"
    )
    args = argp.parse_args()

    settings = get_settings(require_usajobs=True)
    client = USAJobsClient(
        api_key=settings.usajobs_api_key,
        user_agent_email=settings.usajobs_user_agent_email,
        min_request_interval=settings.usajobs_min_request_interval,
        max_calls=args.max_calls,
    )
    counts = run_ingestion(
        client,
        queries=args.queries,
        max_pages_per_query=args.max_pages,
        dry_run=args.dry_run,
    )
    for query, n in counts.items():
        logger.info("Query %r: %d jobs processed", query, n)
    logger.info("API calls used this run: %d / %d", client.calls_made, args.max_calls)
    if not args.dry_run:
        summarize()


if __name__ == "__main__":
    main()
