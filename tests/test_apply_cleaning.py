"""Integration tests for the cleaning pipeline (real Postgres)."""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.cleaning.apply_cleaning import (
    apply_companies,
    apply_metro,
    apply_salary_quality,
    apply_seniority,
)
from src.utils.db import session_scope
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture()
def seeded_db(tmp_path):
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


def run_all(tmp_path: Path) -> dict:
    with session_scope(TEST_DB_URL) as session:
        return {
            "seniority": apply_seniority(session),
            "salary": apply_salary_quality(session),
            "companies": apply_companies(session, tmp_path / "candidates.csv"),
        }


def test_cleaning_applies_and_is_idempotent(seeded_db, tmp_path):
    first = run_all(tmp_path)
    second = run_all(tmp_path)
    assert first == second, "re-running the cleaning layer must converge"

    with seeded_db.connect() as conn:
        # fixture titles include 'Junior Data Analyst' and 'Sr. Data Analyst (Hybrid)'
        junior = conn.execute(
            text(
                "select count(*) from jobs where title = 'Junior Data Analyst' and seniority != 'junior'"
            )
        ).scalar_one()
        senior = conn.execute(
            text("select count(*) from jobs where title like 'Sr.%' and seniority != 'senior'")
        ).scalar_one()
        assert junior == 0 and senior == 0

        # every disclosed salary got a flag; every undisclosed stayed NULL
        unflagged = conn.execute(
            text(
                "select count(*) from jobs where salary_min is not null and salary_quality is null"
            )
        ).scalar_one()
        wrongly_flagged = conn.execute(
            text(
                "select count(*) from jobs where salary_min is null and salary_max is null "
                "and salary_quality is not null"
            )
        ).scalar_one()
        assert unflagged == 0 and wrongly_flagged == 0


def test_meta_variants_share_normalized_name(seeded_db, tmp_path):
    run_all(tmp_path)
    with seeded_db.connect() as conn:
        keys = (
            conn.execute(
                text(
                    "select distinct normalized_name from companies "
                    "where canonical_name in ('Meta', 'Meta Platforms Inc')"
                )
            )
            .scalars()
            .all()
        )
    assert keys == ["meta"], f"Meta variants must collapse to one key, got {keys}"


def test_metro_assignment_on_fixture_locations(seeded_db, tmp_path):
    with session_scope(TEST_DB_URL) as session:
        dist = apply_metro(session)
    # fixture cities include Fairfax VA, New York, San Francisco, ...
    assert dist.get("DC", 0) > 0
    assert dist.get("NYC", 0) > 0
    with seeded_db.connect() as conn:
        wrong = conn.execute(
            text("select count(*) from locations where city = 'Fairfax' and metro_area != 'DC'")
        ).scalar_one()
    assert wrong == 0


def test_candidates_csv_written_for_review(seeded_db, tmp_path):
    out = tmp_path / "candidates.csv"
    with session_scope(TEST_DB_URL) as session:
        apply_companies(session, out)
    content = out.read_text()
    assert content.startswith("name_a,name_b,relation,similarity,approved")
