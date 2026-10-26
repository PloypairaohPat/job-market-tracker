"""The two dashboard views (v_ingestion_runs, v_market_jobs) on the full demo data."""

import os

import pytest
from sqlalchemy import create_engine, text

from scripts.seed_demo_data import seed_full
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path_factory.mktemp("v") / "c.csv")
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def rows(engine, sql):
    with engine.connect() as conn:
        return conn.execute(text(sql)).all()


def columns(engine, view):
    return [
        r.column_name
        for r in rows(
            engine,
            "select column_name from information_schema.columns "
            f"where table_name = '{view}' order by ordinal_position",
        )
    ]


def test_market_jobs_matches_the_completeness_population(demo):
    by_market = dict(rows(demo, "select market, count(*) from v_market_jobs group by market"))
    completeness = dict(rows(demo, "select market, n_jobs from v_field_completeness"))
    assert by_market == completeness  # same population definition, both markets present
    assert set(by_market) == {"commercial", "federal"}
    # out-of-scope federal postings are excluded
    (out_of_scope,) = rows(
        demo,
        "select count(*) from v_market_jobs m join jobs j on j.id = m.job_id "
        "where j.source = 'usajobs' and not j.in_scope",
    )[0]
    assert out_of_scope == 0
    # NULL seniority / metro survive as NULL (never folded into a bucket)
    nulls = rows(
        demo,
        "select count(*) filter (where seniority is null), "
        "count(*) filter (where metro_area is null) from v_market_jobs",
    )[0]
    assert nulls[0] > 0 and nulls[1] > 0
    assert "salary_min" not in columns(demo, "v_market_jobs")


def test_ingestion_runs_mirrors_the_run_log_without_error_or_params(demo):
    (n_view,) = rows(demo, "select count(*) from v_ingestion_runs")[0]
    (n_table,) = rows(demo, "select count(*) from ingestion_runs")[0]
    assert n_view == n_table > 0
    cols = columns(demo, "v_ingestion_runs")
    assert "error" not in cols and "params" not in cols
    statuses = {r.status for r in rows(demo, "select distinct status from v_ingestion_runs")}
    assert {"ok", "failed", "skipped_budget"} <= statuses
