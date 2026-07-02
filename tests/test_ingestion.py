"""Integration tests for the ingestion pipeline against a real Postgres.

Requires TEST_DATABASE_URL (or falls back to DATABASE_URL suffixed with
`_test` semantics is deliberately avoided — be explicit). Skipped when
no test database is configured, so `pytest` still passes on machines
without Postgres running.

These tests verify the Phase 1 acceptance criteria directly:
  - ingestion runs end-to-end without errors
  - re-running produces ZERO duplicate rows in jobs
  - every job row has non-null raw_response_id (+ company/location when present)
  - job_snapshots gets one row per job per day
"""

import copy
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text

from src.ingestion.adzuna_client import AdzunaClient
from src.ingestion.ingest_adzuna import run_ingestion
from src.models import Base, Company, Job, JobSnapshot, Location, RawResponse

FIXTURES = Path(__file__).parent / "fixtures"

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


class FixtureBackedClient(AdzunaClient):
    """AdzunaClient whose iter_search serves local fixture pages.

    Subclassing (rather than a full mock) keeps the pagination contract
    identical to production; only the network fetch is replaced.
    """

    def __init__(self):
        super().__init__(app_id="test", app_key="test", min_request_interval=0.0)
        self._pages = [
            json.loads((FIXTURES / "adzuna_page_1.json").read_text()),
            json.loads((FIXTURES / "adzuna_page_2.json").read_text()),
        ]

    def iter_search(self, query, max_results=1000, results_per_page=50, **filters):
        for i, page in enumerate(self._pages, start=1):
            if (i - 1) * results_per_page >= max_results:
                break
            yield i, copy.deepcopy(page)


@pytest.fixture()
def db():
    """Fresh schema per test."""
    engine = create_engine(TEST_DB_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    # reset the process-wide session factory used by session_scope
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def counts(engine) -> dict:
    with engine.connect() as conn:
        return {
            t.__tablename__: conn.execute(select(func.count()).select_from(t)).scalar_one()
            for t in (Job, Company, Location, RawResponse, JobSnapshot)
        }


def test_ingestion_end_to_end(db):
    client = FixtureBackedClient()
    result = run_ingestion(client, queries=["data analyst"], database_url=TEST_DB_URL)
    assert result["data analyst"] == 100

    c = counts(db)
    assert c["jobs"] == 100
    assert c["raw_responses"] == 2  # one per page, stored verbatim
    assert c["job_snapshots"] == 100  # one snapshot per job today
    assert c["companies"] > 0
    assert c["locations"] > 0

    # every job links back to its raw response (the insurance policy)
    with db.connect() as conn:
        orphans = conn.execute(
            text("select count(*) from jobs where raw_response_id is null")
        ).scalar_one()
        assert orphans == 0


def test_reingestion_is_idempotent(db):
    """The single most important Phase 1 property."""
    client = FixtureBackedClient()
    run_ingestion(client, queries=["data analyst"], database_url=TEST_DB_URL)
    first = counts(db)

    client2 = FixtureBackedClient()
    run_ingestion(client2, queries=["data analyst"], database_url=TEST_DB_URL)
    second = counts(db)

    assert second["jobs"] == first["jobs"], "re-run must not create duplicate jobs"
    assert second["companies"] == first["companies"]
    assert second["locations"] == first["locations"]
    assert second["job_snapshots"] == first["job_snapshots"]  # same day -> same snapshot rows
    # raw responses DO accumulate — every fetch is evidence, by design
    assert second["raw_responses"] == first["raw_responses"] * 2


def test_reingestion_refreshes_last_seen_at(db):
    client = FixtureBackedClient()
    run_ingestion(client, queries=["data analyst"], database_url=TEST_DB_URL)
    with db.connect() as conn:
        before = conn.execute(text("select max(last_seen_at) from jobs")).scalar_one()

    client2 = FixtureBackedClient()
    run_ingestion(client2, queries=["data analyst"], database_url=TEST_DB_URL)
    with db.connect() as conn:
        after = conn.execute(text("select max(last_seen_at) from jobs")).scalar_one()
        first_seen_distinct = conn.execute(
            text("select count(distinct first_seen_at) from jobs")
        ).scalar_one()

    assert after > before, "last_seen_at must advance on re-observation"
    assert first_seen_distinct >= 1  # first_seen_at preserved (not overwritten to 'after')
    with db.connect() as conn:
        overwritten = conn.execute(
            text("select count(*) from jobs where first_seen_at = last_seen_at")
        ).scalar_one()
        assert overwritten == 0, "first_seen_at must NOT be overwritten on re-ingestion"


def test_null_location_components_do_not_duplicate(db):
    """('US', 'Virginia', NULL) must resolve to ONE location row across runs.

    This is the Postgres NULLs-are-distinct trap the upsert works around.
    """
    client = FixtureBackedClient()
    run_ingestion(client, queries=["data analyst"], database_url=TEST_DB_URL)
    run_ingestion(FixtureBackedClient(), queries=["data analyst"], database_url=TEST_DB_URL)
    with db.connect() as conn:
        dupes = conn.execute(
            text(
                """
            select count(*) from (
                select country, state, city, count(*) as n
                from locations
                group by country, state, city
                having count(*) > 1
            ) d
            """
            )
        ).scalar_one()
    assert dupes == 0


def test_demo_seeder_is_idempotent_across_processes(db):
    """The demo seeder must produce stable external IDs across separate
    Python processes (regression: hash() randomization duplicated rows)."""
    import subprocess
    import sys

    env = dict(os.environ, DATABASE_URL=TEST_DB_URL)
    root = Path(__file__).parent.parent
    for _ in range(2):
        subprocess.run(
            [sys.executable, "scripts/seed_demo_data.py"],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
        )
    with db.connect() as conn:
        n = conn.execute(text("select count(*) from jobs")).scalar_one()
    assert n == 600, f"expected 600 jobs after two seed runs, got {n}"
