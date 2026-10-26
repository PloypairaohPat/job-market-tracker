"""`seed_demo_data.py --full`: the dashboard demo dataset."""

import os
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text

from scripts.seed_demo_data import seed_full
from src.dashboard.demo_dataset import UnsafeDemoDatabaseError, assert_demo_database
from src.models import Base
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/jobmarket",  # the real one
        "postgresql+psycopg2://postgres:postgres@localhost:5432/postgres",
        "postgresql+psycopg2://postgres:postgres@db.example.com:5432/jobmarket_demo",
    ],
)
def test_full_mode_refuses_non_demo_databases(url):
    with pytest.raises(UnsafeDemoDatabaseError):
        assert_demo_database(url)


def test_full_mode_accepts_local_demo_and_test_databases():
    assert_demo_database("postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/jobmarket_demo")
    assert_demo_database("postgresql+psycopg2://postgres:postgres@localhost:5432/jobmarket_test")


# --------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    if not TEST_DB_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    out = tmp_path_factory.mktemp("demo") / "candidates.csv"
    counts = seed_full(TEST_DB_URL, candidates_out=out)
    yield engine, counts, out
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def q(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).all()


def fingerprint(engine) -> dict[str, str]:
    """md5 of every table's full contents, order-independent."""
    out = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            out[table.name] = conn.execute(
                text(
                    f"select md5(coalesce(string_agg(t::text, '|' order by t::text), '')) "
                    f"from {table.name} t"
                )
            ).scalar_one()
    return out


@pytest.mark.integration
def test_two_markets(seeded):
    engine, counts, _ = seeded
    assert {r.market for r in q(engine, "select market from v_field_completeness")} == {
        "commercial",
        "federal",
    }
    assert all(n > 0 for n in counts.values()), counts


@pytest.mark.integration
def test_snapshot_history_has_exactly_one_gap(seeded):
    engine, _, _ = seeded
    dates = sorted(
        {r.snapshot_date for r in q(engine, "select snapshot_date from v_ingestion_daily")}
    )
    assert len(dates) >= 20
    span = (dates[-1] - dates[0]).days + 1
    missing = [dates[0] + timedelta(days=i) for i in range(span)]
    missing = [d for d in missing if d not in set(dates)]
    assert len(missing) == 1, missing
    statuses = {r.status for r in q(engine, "select distinct status from ingestion_runs")}
    assert {"ok", "failed", "skipped_budget"} <= statuses
    # first/last_seen follow the synthetic history
    bad = q(
        engine,
        "select j.id from jobs j join job_snapshots s on s.job_id = j.id group by j.id "
        "having min(s.snapshot_date) <> (j.first_seen_at at time zone 'UTC')::date "
        "or max(s.snapshot_date) <> (j.last_seen_at at time zone 'UTC')::date",
    )
    assert bad == []


@pytest.mark.integration
def test_every_visa_bucket(seeded):
    engine, _, _ = seeded
    buckets = {r.bucket for r in q(engine, "select distinct bucket from v_job_visa_outlook")}
    assert buckets == {"closed", "strong", "possible", "unknown"}


@pytest.mark.integration
def test_synthetic_sponsorship_data_only_under_fake_names(seeded):
    engine, _, _ = seeded
    lca_employers = q(engine, "select distinct employer_name from lca_cases")
    assert lca_employers and all("FAKE" in r.employer_name for r in lca_employers)
    companies_with_lca = q(
        engine,
        "select distinct c.canonical_name from companies c "
        "join lca_cases l on l.employer_key = c.normalized_name",
    )
    assert companies_with_lca and all("FAKE" in r.canonical_name for r in companies_with_lca)
    sponsorship_jobs = q(
        engine,
        "select c.canonical_name from jobs j "
        "join job_visa_signals s on s.job_id = j.id "
        "left join companies c on c.id = j.company_id "
        "where s.sponsorship_stance <> 'none_found' or s.opt_mentioned "
        "or coalesce(j.description_full, j.description) ilike '%sponsor%'",
    )
    assert sponsorship_jobs and all("FAKE" in (r.canonical_name or "") for r in sponsorship_jobs)


@pytest.mark.integration
def test_rerun_is_deterministic_and_idempotent(seeded):
    engine, counts, out = seeded
    before = fingerprint(engine)
    assert seed_full(TEST_DB_URL, candidates_out=out) == counts
    assert fingerprint(engine) == before
