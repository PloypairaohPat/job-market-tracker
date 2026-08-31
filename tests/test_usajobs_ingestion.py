"""Integration tests for the USAJobs ingestion pipeline against a real Postgres.

Mirrors tests/test_ingestion.py's Adzuna coverage: idempotency is the
property that matters most for a re-run pipeline.
"""

import copy
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text

from src.ingestion.ingest_usajobs import backfill_from_raw_responses, run_ingestion
from src.ingestion.usajobs_client import USAJobsClient
from src.models import Company, Job, JobSnapshot, Location, RawResponse
from src.utils.db import session_scope
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


class RecordingClient(USAJobsClient):
    """Records the (query, filters) each iter_search call received, and
    returns one canned page regardless -- for verifying run_ingestion
    builds the right search parameters, independent of real results."""

    def __init__(self):
        super().__init__(api_key="test", user_agent_email="test@example.com", min_request_interval=0.0)
        self.calls: list[tuple[str | None, dict]] = []
        self._page = {
            "SearchResult": {
                "SearchResultCountAll": 1,
                "SearchResultItems": [
                    {
                        "MatchedObjectId": "1",
                        "MatchedObjectDescriptor": {"PositionTitle": "x", "DepartmentName": "Dept"},
                    }
                ],
            }
        }

    def iter_search(self, query=None, max_results=1000, results_per_page=25, **filters):
        self.calls.append((query, filters))
        yield 1, copy.deepcopy(self._page)


def test_series_code_ingestion_is_opt_in(db):
    """series_codes defaults to None (skip) -- unlike queries, it must
    NOT silently default to TARGET_SERIES_CODES, or every existing
    caller (including other tests) would start issuing extra searches."""
    client = RecordingClient()
    run_ingestion(client, queries=["data analyst"], database_url=TEST_DB_URL)
    assert client.calls == [("data analyst", {})]


def test_series_code_ingestion_sends_job_category_code_not_keyword(db):
    client = RecordingClient()
    counts = run_ingestion(
        client, queries=[], series_codes=["1560"], database_url=TEST_DB_URL
    )
    assert client.calls == [(None, {"JobCategoryCode": "1560"})]
    assert counts == {"series:1560": 1}

    with db.connect() as conn:
        params = conn.execute(select(RawResponse.params)).scalar_one()
    assert params == {"JobCategoryCode": "1560", "Page": 1}
    assert "Keyword" not in params


def test_reingestion_does_not_null_out_description_full(db):
    """description_full must survive re-observation, not just first insert."""
    run_ingestion(FixtureBackedClient(), queries=["data analyst"], database_url=TEST_DB_URL)
    run_ingestion(FixtureBackedClient(), queries=["data analyst"], database_url=TEST_DB_URL)

    with db.connect() as conn:
        n_with_full = conn.execute(
            select(func.count()).select_from(Job).where(Job.description_full.is_not(None))
        ).scalar_one()
    assert n_with_full > 0


def test_backfill_from_raw_responses_refreshes_category(db):
    """Real case: job 865002200 is tagged both General Engineering and
    Operations Research. Simulates the pre-fix state (job row has only
    the stale first-label category; the stored raw response always had
    both) and confirms backfill corrects it -- without any network call,
    the raw-then-normalized pattern applied to a parser bugfix."""
    raw_payload = {
        "SearchResult": {
            "SearchResultItems": [
                {
                    "MatchedObjectId": "865002200",
                    "MatchedObjectDescriptor": {
                        "PositionTitle": "INTERDISCIPLINARY GENERAL ENGINEER/OPERATIONS RESEARCH ANALYST",
                        "JobCategory": [
                            {"Code": "0801", "Name": "General Engineering"},
                            {"Code": "1515", "Name": "Operations Research"},
                        ],
                    },
                }
            ]
        }
    }
    with session_scope(TEST_DB_URL) as session:
        raw = RawResponse(source="usajobs", endpoint="/api/search", params={}, response=raw_payload)
        session.add(raw)
        session.flush()
        session.add(
            Job(
                external_id="865002200",
                source="usajobs",
                title="stale title",
                category="General Engineering",  # stale: pre-fix, first label only
                raw_response_id=raw.id,
            )
        )

    with session_scope(TEST_DB_URL) as session:
        n = backfill_from_raw_responses(session)
    assert n == 1

    with db.connect() as conn:
        category = conn.execute(
            text("select category from jobs where external_id = '865002200'")
        ).scalar_one()
    assert "General Engineering" in category
    assert "Operations Research" in category

    # no new raw_responses row, no job_snapshots row -- pure data repair
    with db.connect() as conn:
        raw_count = conn.execute(select(func.count()).select_from(RawResponse)).scalar_one()
        snap_count = conn.execute(select(func.count()).select_from(JobSnapshot)).scalar_one()
    assert raw_count == 1
    assert snap_count == 0


def test_backfill_from_raw_responses_is_idempotent(db):
    raw_payload = {
        "SearchResult": {
            "SearchResultItems": [
                {
                    "MatchedObjectId": "1",
                    "MatchedObjectDescriptor": {"PositionTitle": "x", "DepartmentName": "Dept"},
                }
            ]
        }
    }
    with session_scope(TEST_DB_URL) as session:
        raw = RawResponse(source="usajobs", endpoint="/api/search", params={}, response=raw_payload)
        session.add(raw)
        session.flush()
        session.add(Job(external_id="1", source="usajobs", title="x", raw_response_id=raw.id))

    with session_scope(TEST_DB_URL) as session:
        first = backfill_from_raw_responses(session)
    with session_scope(TEST_DB_URL) as session:
        second = backfill_from_raw_responses(session)
    assert first == second == 1

    with db.connect() as conn:
        job_count = conn.execute(select(func.count()).select_from(Job)).scalar_one()
    assert job_count == 1
