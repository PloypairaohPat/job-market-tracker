"""Integration tests for the apply_cleaning `visa` step (real Postgres).

Seeds from the existing Adzuna and USAJobs fixtures -- no network calls.
"""

import os

import pytest
from sqlalchemy import create_engine, text

from src.cleaning.apply_cleaning import apply_visa
from src.utils.db import session_scope
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]

_COMPARABLE = (
    "select job_id, restriction, restriction_reason, sponsorship_stance, sponsorship_reason, "
    "opt_mentioned, text_coverage, cap_exempt_hint, cap_exempt_reason "
    "from job_visa_signals order by job_id"
)


@pytest.fixture()
def seeded_db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)

    from src.ingestion.ingest_adzuna import run_ingestion as run_adzuna
    from src.ingestion.ingest_usajobs import run_ingestion as run_usajobs
    from tests.test_ingestion import FixtureBackedClient as AdzunaFixtureClient
    from tests.test_usajobs_ingestion import FixtureBackedClient as USAJobsFixtureClient

    run_adzuna(AdzunaFixtureClient(), queries=["data analyst"], database_url=TEST_DB_URL)
    run_usajobs(USAJobsFixtureClient(), queries=["data analyst"], database_url=TEST_DB_URL)
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def test_visa_step_is_idempotent(seeded_db):
    with session_scope(TEST_DB_URL) as session:
        first_dist = apply_visa(session)
    with seeded_db.connect() as conn:
        first = conn.execute(text(_COMPARABLE)).all()
        n_jobs = conn.execute(text("select count(*) from jobs")).scalar_one()

    with session_scope(TEST_DB_URL) as session:
        second_dist = apply_visa(session)
    with seeded_db.connect() as conn:
        second = conn.execute(text(_COMPARABLE)).all()

    assert first_dist == second_dist
    assert first == second  # same table; only classified_at moves
    assert len(first) == n_jobs  # one row per job, no duplicates


def test_visa_step_reads_usajobs_key_requirements_from_raw_response(seeded_db):
    with session_scope(TEST_DB_URL) as session:
        apply_visa(session)
    with seeded_db.connect() as conn:
        rows = {
            r.external_id: r
            for r in conn.execute(
                text(
                    "select j.external_id, j.source, s.restriction, s.restriction_reason, "
                    "s.text_coverage from job_visa_signals s join jobs j on j.id = s.job_id"
                )
            )
        }
    structured = rows["880660900"]
    assert (structured.restriction, structured.restriction_reason) == (
        "citizenship",
        "usajobs KeyRequirements",
    )
    usajobs = [r for r in rows.values() if r.source == "usajobs"]
    assert sum(r.restriction == "citizenship" for r in usajobs) >= 11  # 1 structured + 10 text
    assert all(r.text_coverage == "full" for r in usajobs)
    assert all(r.text_coverage == "truncated" for r in rows.values() if r.source == "adzuna")
