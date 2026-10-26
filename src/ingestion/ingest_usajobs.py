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
from src.ingestion.run_log import RunStats, recorded_run
from src.ingestion.usajobs_client import CallBudgetExceeded, USAJobsClient
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

# Occupational series confirmed unambiguously quantitative/analytics via
# GET /api/codelist/occupationalseries and validated against real search
# counts (docs/data_dictionary.md): 1560 Data Science Series, 1515
# Operations Research, 1530 Statistics. Deliberately excludes 0343
# (Management And Program Analysis) and 2210 (IT Management) -- both
# stay huge (229/271 results) even combined with a keyword filter, so
# series-code querying doesn't clean them up; they're handled by the
# relevance layer (src/cleaning/scope_classifier.py) instead.
TARGET_SERIES_CODES = ["1560", "1515", "1530"]

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


def ingest_page(session: Session, query_params: dict, page: int, response: dict) -> int:
    """Persist one raw page + all its jobs. Returns jobs processed.

    `query_params` records what was actually searched (`{"Keyword": ...}`
    or `{"JobCategoryCode": ...}`) for the raw_responses audit trail --
    it's not necessarily a keyword, since series-code searches carry none.
    """
    now = datetime.now(UTC)
    today = now.date()
    items = response.get("SearchResult", {}).get("SearchResultItems", [])
    raw_id = save_raw_response(
        session,
        endpoint="/api/search",
        params={**query_params, "Page": page},
        response=response,
    )
    processed = 0
    for raw_job in items:
        try:
            job_fields = parser.parse_job(raw_job)
        except KeyError:
            logger.warning(
                "Skipping result with no MatchedObjectId in %r page %d", query_params, page
            )
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
    series_codes: list[str] | None = None,
    max_pages_per_query: int = 5,
    results_per_page: int = 25,
    dry_run: bool = False,
    database_url: str | None = None,
    stats: RunStats | None = None,
) -> dict[str, int]:
    """Full ingestion across all target queries and (optionally) series codes.

    `queries` defaults to TARGET_QUERIES when None. `series_codes` is
    opt-in -- None means "run keyword search only" (unlike `queries`, it
    does NOT default to TARGET_SERIES_CODES) so existing callers get
    unchanged behavior; `main()` passes TARGET_SERIES_CODES explicitly
    for real runs. Series-code search exists because keyword search
    structurally cannot find some series -- confirmed live: 23 real Data
    Science (series 1560) postings exist, and combining
    `Keyword=data analyst`+`JobCategoryCode=1560` still returns zero.

    Returns per-search counts, keyed by the query string for keyword
    searches (unchanged from before) and `"series:<code>"` for series
    searches.
    """
    queries = TARGET_QUERIES if queries is None else queries
    series_codes = series_codes or []
    counts: dict[str, int] = {}

    searches: list[tuple[str, dict]] = [(q, {"query": q}) for q in queries]
    searches += [
        (f"series:{code}", {"query": None, "JobCategoryCode": code}) for code in series_codes
    ]

    for label, search_kwargs in searches:
        counts[label] = 0
        query_params = (
            {"JobCategoryCode": search_kwargs["JobCategoryCode"]}
            if "JobCategoryCode" in search_kwargs
            else {"Keyword": search_kwargs["query"]}
        )
        try:
            for page, response in client.iter_search(
                max_results=max_pages_per_query * results_per_page,
                results_per_page=results_per_page,
                **search_kwargs,
            ):
                if dry_run:
                    n = len(response.get("SearchResult", {}).get("SearchResultItems", []))
                    logger.info("[dry-run] %r page %d: %d results (not persisted)", label, page, n)
                    counts[label] += n
                    continue
                with session_scope(database_url) as session:
                    n = ingest_page(session, query_params, page, response)
                counts[label] += n
                if stats is not None:
                    stats.pages_fetched += 1
                    stats.jobs_processed += n
        except CallBudgetExceeded as exc:
            logger.error("Stopping: %s", exc)
            if stats is not None:
                stats.budget_cut = True
            break
    return counts


def backfill_from_raw_responses(session: Session) -> int:
    """Re-parse every stored USAJobs raw_responses row and refresh the
    matching jobs' derived fields -- without any network call. The
    raw-then-normalized pattern applied to a parser bugfix: replay
    history, don't re-fetch (e.g. the `category` multi-label fix means
    already-ingested rows can hold a stale, incomplete value).

    Does not touch job_snapshots (this is a data-repair pass, not a new
    observation) and never creates new raw_responses rows. Every item in
    every stored page already has a matching job row by (source,
    external_id), so this only ever hits the ON CONFLICT UPDATE branch.
    """
    now = datetime.now(UTC)
    raw_rows = session.execute(
        select(RawResponse.id, RawResponse.response).where(RawResponse.source == parser.SOURCE)
    ).all()
    processed = 0
    for raw_id, response in raw_rows:
        items = response.get("SearchResult", {}).get("SearchResultItems", [])
        for raw_job in items:
            try:
                job_fields = parser.parse_job(raw_job)
            except KeyError:
                continue
            company_id = upsert_company(session, parser.parse_company(raw_job))
            location_id = upsert_location(session, parser.parse_location(raw_job))
            upsert_job(session, job_fields, company_id, location_id, raw_id, now)
            processed += 1
    return processed


def build_client(settings: Settings, max_calls: int) -> USAJobsClient:
    """A USAJobsClient from Settings (raises USAJobsError if credentials are empty)."""
    return USAJobsClient(
        api_key=settings.usajobs_api_key,
        user_agent_email=settings.usajobs_user_agent_email,
        min_request_interval=settings.usajobs_min_request_interval,
        max_calls=max_calls,
    )


def run_logged(
    client: USAJobsClient,
    queries: list[str] | None = None,
    series_codes: list[str] | None = None,
    max_pages_per_query: int = 5,
    database_url: str | None = None,
) -> tuple[dict[str, int], RunStats]:
    """run_ingestion wrapped in an ingestion_runs row (see run_log.py).
    Re-raises after recording a failure."""
    params = {
        "queries": TARGET_QUERIES if queries is None else queries,
        "series_codes": series_codes or [],
        "max_pages": max_pages_per_query,
        "max_calls": client.max_calls,
        "dry_run": False,
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
            series_codes=series_codes,
            max_pages_per_query=max_pages_per_query,
            database_url=database_url,
            stats=stats,
        )
    return counts, stats


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
    argp.add_argument(
        "--series-codes",
        nargs="*",
        default=TARGET_SERIES_CODES,
        help=(
            "Occupational series codes to query directly, in addition to "
            "keyword search (default: the 3 confirmed-clean series -- "
            "Data Science 1560, Operations Research 1515, Statistics "
            "1530). Pass no arguments to disable."
        ),
    )
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
    argp.add_argument(
        "--backfill-from-raw",
        action="store_true",
        help=(
            "Re-parse stored raw_responses and refresh derived job fields "
            "without fetching anything (no API credentials needed). Use "
            "after a parser fix; ignores all other flags."
        ),
    )
    args = argp.parse_args()

    if args.backfill_from_raw:
        with session_scope() as session:
            n = backfill_from_raw_responses(session)
        logger.info("Backfilled %d jobs from stored raw_responses.", n)
        return

    settings = get_settings(require_usajobs=True)
    install_redaction(secrets_from_settings(settings))
    client = build_client(settings, args.max_calls)
    if args.dry_run:
        counts = run_ingestion(
            client,
            queries=args.queries,
            series_codes=args.series_codes,
            max_pages_per_query=args.max_pages,
            dry_run=True,
        )
    else:
        counts, _ = run_logged(
            client,
            queries=args.queries,
            series_codes=args.series_codes,
            max_pages_per_query=args.max_pages,
        )
    for query, n in counts.items():
        logger.info("Query %r: %d jobs processed", query, n)
    logger.info("API calls used this run: %d / %d", client.calls_made, args.max_calls)
    if not args.dry_run:
        summarize()


if __name__ == "__main__":
    main()
