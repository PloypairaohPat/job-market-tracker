"""Integration tests for the skill extraction backfill (real Postgres)."""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.cleaning.extract_skills import extract_for_all_jobs, sync_taxonomy
from src.utils.db import session_scope
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def seeded_db():
    """Fresh schema + demo jobs via the real ingestion pipeline."""
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)

    from src.ingestion.ingest_adzuna import run_ingestion
    from tests.test_ingestion import FixtureBackedClient

    run_ingestion(FixtureBackedClient(), queries=["data analyst"], database_url=TEST_DB_URL)
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def counts(engine) -> tuple[int, int]:
    with engine.connect() as conn:
        skills = conn.execute(text("select count(*) from skills")).scalar_one()
        links = conn.execute(text("select count(*) from job_skills")).scalar_one()
    return skills, links


def test_backfill_extracts_and_is_idempotent(seeded_db):
    with session_scope(TEST_DB_URL) as session:
        skill_ids = sync_taxonomy(session)
        jobs, links = extract_for_all_jobs(session, skill_ids)
    assert jobs == 100
    assert links > 0, "fixture descriptions mention SQL/Python/Tableau — links expected"

    skills_1, links_1 = counts(seeded_db)
    assert skills_1 >= 50

    # second run must converge, not accumulate
    with session_scope(TEST_DB_URL) as session:
        skill_ids = sync_taxonomy(session)
        extract_for_all_jobs(session, skill_ids)
    skills_2, links_2 = counts(seeded_db)
    assert (skills_2, links_2) == (skills_1, links_1)


def test_backfill_finds_expected_fixture_skills(seeded_db):
    with session_scope(TEST_DB_URL) as session:
        skill_ids = sync_taxonomy(session)
        extract_for_all_jobs(session, skill_ids)
    with seeded_db.connect() as conn:
        top = dict(
            conn.execute(
                text(
                    """
                    select s.name, count(*) from job_skills js
                    join skills s on s.id = js.skill_id
                    group by s.name
                    """
                )
            ).all()
        )
    # fixture snippets explicitly mention these
    for expected in ("SQL", "Python", "Tableau", "Excel", "Power BI", "Looker", "dbt", "Snowflake"):
        assert expected in top, f"{expected} should be extracted from fixture descriptions"
