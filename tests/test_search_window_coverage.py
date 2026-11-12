"""D1: v_search_window_coverage on hand-built raw_responses rows (invented numbers)."""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture()
def engine():
    eng = create_engine(TEST_DB_URL)
    reset_schema(eng)
    apply_views(TEST_DB_URL)
    yield eng
    eng.dispose()


def adzuna(conn, when, query, page, n_results, count):
    response = {"count": count, "results": [{"id": str(i)} for i in range(n_results)]}
    conn.execute(
        text(
            "insert into raw_responses (source, fetched_at, endpoint, params, response) "
            "values ('adzuna', :at, :ep, cast(:p as jsonb), cast(:r as jsonb))"
        ),
        {
            "at": when,
            "ep": f"/jobs/us/search/{page}",
            "p": json.dumps({"what": query, "page": page}),
            "r": json.dumps(response),
        },
    )


def usajobs(conn, when, params, page, n_results, total):
    response = {
        "SearchResult": {
            "SearchResultCount": n_results,
            "SearchResultCountAll": total,
            "SearchResultItems": [{"MatchedObjectId": str(i)} for i in range(n_results)],
        }
    }
    conn.execute(
        text(
            "insert into raw_responses (source, fetched_at, endpoint, params, response) "
            "values ('usajobs', :at, '/api/search', cast(:p as jsonb), cast(:r as jsonb))"
        ),
        {"at": when, "p": json.dumps({**params, "Page": page}), "r": json.dumps(response)},
    )


def rows(engine):
    with engine.connect() as conn:
        return {
            (r.source, str(r.fetch_date), r.query): r
            for r in conn.execute(text("select * from v_search_window_coverage"))
        }


def test_columns_are_stable(engine):
    with engine.connect() as conn:
        cols = conn.execute(text("select * from v_search_window_coverage limit 0")).keys()
    assert list(cols) == [
        "source",
        "fetch_date",
        "query",
        "n_responses",
        "pages_stored",
        "results_captured",
        "api_total",
        "pct_captured",
    ]


def test_total_below_the_window_is_fully_captured(engine):
    with engine.begin() as conn:
        adzuna(conn, "2026-10-01 11:00+00", "product analyst", 1, 50, 73)
        adzuna(conn, "2026-10-01 11:01+00", "product analyst", 2, 23, 73)
    r = rows(engine)[("adzuna", "2026-10-01", "product analyst")]
    assert (r.n_responses, r.pages_stored, r.results_captured, r.api_total) == (2, 2, 73, 73)
    assert float(r.pct_captured) == 100.0


def test_total_far_above_the_window(engine):
    with engine.begin() as conn:
        for page in range(1, 6):
            adzuna(conn, f"2026-10-01 11:0{page}+00", "data analyst", page, 50, 5000)
    r = rows(engine)[("adzuna", "2026-10-01", "data analyst")]
    assert (r.pages_stored, r.results_captured, r.api_total) == (5, 250, 5000)
    assert float(r.pct_captured) == 5.0


def test_partial_run_then_a_retry_counts_each_page_once(engine):
    with engine.begin() as conn:
        # partial run: two pages, then a failure
        adzuna(conn, "2026-10-02 07:15+00", "data analyst", 1, 50, 1000)
        adzuna(conn, "2026-10-02 07:16+00", "data analyst", 2, 50, 1000)
        # retry the same UTC day: pages 1-3, total drifted
        adzuna(conn, "2026-10-02 13:15+00", "data analyst", 1, 50, 1004)
        adzuna(conn, "2026-10-02 13:16+00", "data analyst", 2, 50, 1004)
        adzuna(conn, "2026-10-02 13:17+00", "data analyst", 3, 40, 1004)
    r = rows(engine)[("adzuna", "2026-10-02", "data analyst")]
    assert (r.n_responses, r.pages_stored, r.results_captured, r.api_total) == (5, 3, 140, 1004)
    assert float(r.pct_captured) == 13.9


def test_a_day_with_only_some_queries(engine):
    with engine.begin() as conn:
        adzuna(conn, "2026-10-03 11:00+00", "data analyst", 1, 50, 900)
        adzuna(conn, "2026-10-04 11:00+00", "data analyst", 1, 50, 900)
        adzuna(conn, "2026-10-04 11:01+00", "marketing analyst", 1, 50, 400)
    r = rows(engine)
    assert ("adzuna", "2026-10-03", "marketing analyst") not in r  # a gap, never a zero row
    assert ("adzuna", "2026-10-04", "marketing analyst") in r


def test_fetch_date_is_utc(engine):
    with engine.begin() as conn:
        adzuna(conn, "2026-10-05 23:30-05:00", "data analyst", 1, 10, 10)  # 04:30 UTC next day
    assert ("adzuna", "2026-10-06", "data analyst") in rows(engine)


def test_usajobs_keyword_and_series_queries(engine):
    with engine.begin() as conn:
        usajobs(conn, "2026-10-01 11:00+00", {"Keyword": "data analyst"}, 1, 25, 234)
        usajobs(conn, "2026-10-01 11:01+00", {"Keyword": "data analyst"}, 2, 25, 234)
        usajobs(conn, "2026-10-01 11:02+00", {"JobCategoryCode": "1560"}, 1, 12, 12)
    r = rows(engine)
    kw = r[("usajobs", "2026-10-01", "data analyst")]
    assert (kw.pages_stored, kw.results_captured, kw.api_total) == (2, 50, 234)
    assert float(kw.pct_captured) == 21.4
    series = r[("usajobs", "2026-10-01", "series:1560")]
    assert float(series.pct_captured) == 100.0


def test_missing_or_zero_total_gives_null_share(engine):
    with engine.begin() as conn:
        adzuna(conn, "2026-10-01 11:00+00", "a", 1, 0, 0)
        conn.execute(
            text(
                "insert into raw_responses (source, fetched_at, endpoint, params, response) "
                "values ('adzuna', '2026-10-01 12:00+00', '/x', "
                """'{"what": "b", "page": 1}', '{"results": [{"id": "1"}]}')"""
            )
        )
    r = rows(engine)
    assert r[("adzuna", "2026-10-01", "a")].pct_captured is None
    assert r[("adzuna", "2026-10-01", "b")].api_total is None
    assert r[("adzuna", "2026-10-01", "b")].pct_captured is None


def test_the_real_fixture_pages_parse(engine):
    """The stored fixtures' shapes: Adzuna count/results, USAJobs CountAll/Items."""
    page = json.loads((FIXTURES / "adzuna_page_1.json").read_text())
    fed = json.loads((FIXTURES / "usajobs_sample_response.json").read_text())
    with engine.begin() as conn:
        conn.execute(
            text(
                "insert into raw_responses (source, fetched_at, endpoint, params, response) values "
                "('adzuna', '2026-10-07 11:00+00', '/jobs/us/search/1', "
                """'{"what": "data analyst", "page": 1}', cast(:a as jsonb)),"""
                "('usajobs', '2026-10-07 11:00+00', '/api/search', "
                """'{"Keyword": "data analyst", "Page": 1}', cast(:u as jsonb))"""
            ),
            {"a": json.dumps(page), "u": json.dumps(fed)},
        )
    r = rows(engine)
    az = r[("adzuna", "2026-10-07", "data analyst")]
    assert (az.results_captured, az.api_total) == (len(page["results"]), page["count"])
    us = r[("usajobs", "2026-10-07", "data analyst")]
    assert us.results_captured == len(fed["SearchResult"]["SearchResultItems"])
    assert us.api_total == fed["SearchResult"]["SearchResultCountAll"]
