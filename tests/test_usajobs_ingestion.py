"""Integration tests for the USAJobs ingestion pipeline against a real Postgres.

Mirrors tests/test_ingestion.py's Adzuna coverage: idempotency is the
property that matters most for a re-run pipeline.
"""

import copy
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select

from src.ingestion.ingest_usajobs import run_ingestion
from src.ingestion.usajobs_client import USAJobsClient
from src.models import Company, Job, JobSnapshot, Location, RawResponse
from tests.conftest import reset_schema

FIXTURES = Path(__file__).parent / "fixtures"

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


class FixtureBackedClient(USAJobsClient):
    """USAJobsClient whose iter_search serves a local fixture page."""

    def __init__(self):
        super().__init__(api_key="test", user_agent_email="test@example.com", min_request_interval=0.0)
        self._page = json.loads((FIXTURES / "usajobs_sample_response.json").read_text())

    def iter_search(self, query, max_results=1000, results_per_page=25, **filters):
        yield 1, copy.deepcopy(self._page)


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    yield engine
    engine.dispose()
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
    result = run_ingestion(FixtureBackedClient(), queries=["data analyst"], database_url=TEST_DB_URL)
    assert result["data analyst"] == 25

    n = counts(db)
    assert n["jobs"] == 25
    assert n["raw_responses"] == 1

    with db.connect() as conn:
        source = conn.execute(select(Job.source).limit(1)).scalar_one()
        assert source == "usajobs"
        raw_source = conn.execute(select(RawResponse.source).limit(1)).scalar_one()
        assert raw_source == "usajobs"


def test_reingestion_is_idempotent(db):
    run_ingestion(FixtureBackedClient(), queries=["data analyst"], database_url=TEST_DB_URL)
    first = counts(db)

    run_ingestion(FixtureBackedClient(), queries=["data analyst"], database_url=TEST_DB_URL)
    second = counts(db)

    # jobs/companies/locations/snapshots never duplicate on re-run
    assert second["jobs"] == first["jobs"] == 25
    assert second["companies"] == first["companies"]
    assert second["locations"] == first["locations"]
    assert second["job_snapshots"] == first["job_snapshots"]
    # raw_responses is the one table that accumulates by design
    assert second["raw_responses"] == first["raw_responses"] + 1


def test_reingestion_does_not_null_out_description_full(db):
    """description_full must survive re-observation, not just first insert."""
    run_ingestion(FixtureBackedClient(), queries=["data analyst"], database_url=TEST_DB_URL)
    run_ingestion(FixtureBackedClient(), queries=["data analyst"], database_url=TEST_DB_URL)

    with db.connect() as conn:
        n_with_full = conn.execute(
            select(func.count()).select_from(Job).where(Job.description_full.is_not(None))
        ).scalar_one()
    assert n_with_full > 0
