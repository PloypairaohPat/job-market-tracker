"""D3: v_job_observation_spans and v_daily_market_flow on hand-built rows.

Commercial (adzuna) snapshot days are Oct 1-3 and 5-8 (Oct 4 missed);
federal (usajobs) has a single snapshot day, Oct 3. Invented data only.
"""

import os
from datetime import date

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]

ALL_ADZUNA_DAYS = [1, 2, 3, 5, 6, 7, 8]
JOBS = {
    # name: (source, in_scope, October days seen)
    "unbroken": ("adzuna", True, [6, 7]),
    "gap_before": ("adzuna", True, [5, 6]),
    "gap_after": ("adzuna", True, [2, 3]),
    "returns": ("adzuna", True, [1, 2, 6]),
    "latest": ("adzuna", True, [7, 8]),
    "every_day": ("adzuna", True, ALL_ADZUNA_DAYS),
    "fed_in": ("usajobs", True, [3]),
    "fed_out": ("usajobs", False, [3]),
}


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(TEST_DB_URL)
    reset_schema(eng)
    apply_views(TEST_DB_URL)
    with eng.begin() as conn:
        for name, (source, in_scope, days) in JOBS.items():
            job_id = conn.execute(
                text(
                    "insert into jobs (external_id, source, title, in_scope, is_remote, "
                    "first_seen_at, last_seen_at) values (:e, :s, 'Analyst', :i, false, now(), now()) "
                    "returning id"
                ),
                {"e": name, "s": source, "i": in_scope},
            ).scalar_one()
            for d in days:
                conn.execute(
                    text(
                        "insert into job_snapshots (job_id, snapshot_date, is_active) "
                        "values (:j, :d, true)"
                    ),
                    {"j": job_id, "d": date(2026, 10, d)},
                )
    yield eng
    eng.dispose()


def spans(engine):
    with engine.connect() as conn:
        return {
            r.external_id: r
            for r in conn.execute(
                text(
                    "select j.external_id, v.* from v_job_observation_spans v "
                    "join jobs j on j.id = v.job_id"
                )
            )
        }


def flow(engine):
    with engine.connect() as conn:
        return {
            (r.market, r.snapshot_date.day): (
                r.jobs_seen,
                r.jobs_first_seen,
                r.jobs_last_seen,
                r.prev_day_has_snapshot,
            )
            for r in conn.execute(text("select * from v_daily_market_flow"))
        }


def test_span_columns(engine):
    with engine.connect() as conn:
        cols = list(conn.execute(text("select * from v_job_observation_spans limit 0")).keys())
    assert cols == [
        "job_id",
        "market",
        "source",
        "first_seen_date",
        "last_seen_date",
        "days_seen",
        "source_days_in_span",
        "entry_is_exact",
        "exit_state",
    ]


def check(row, first, last, days_seen, in_span, entry, exit_state):
    assert (row.first_seen_date.day, row.last_seen_date.day) == (first, last)
    assert (row.days_seen, row.source_days_in_span) == (days_seen, in_span)
    assert row.entry_is_exact is entry
    assert row.exit_state == exit_state


def test_unbroken_run_with_exact_edges(engine):
    check(spans(engine)["unbroken"], 6, 7, 2, 2, True, "exit_exact")


def test_missed_day_before_the_first_sighting(engine):
    check(spans(engine)["gap_before"], 5, 6, 2, 2, False, "exit_exact")


def test_missed_day_after_the_last_sighting(engine):
    check(spans(engine)["gap_after"], 2, 3, 2, 2, True, "exit_in_gap")


def test_a_job_that_disappears_and_returns(engine):
    # first day of the series: entry is never exact
    check(spans(engine)["returns"], 1, 6, 3, 5, False, "exit_exact")


def test_seen_on_the_latest_day_is_still_listed(engine):
    s = spans(engine)
    check(s["latest"], 7, 8, 2, 2, True, "still_listed")
    check(s["every_day"], 1, 8, 7, 7, False, "still_listed")


def test_a_source_with_a_single_snapshot_day(engine):
    row = spans(engine)["fed_in"]
    assert row.market == "federal"
    check(row, 3, 3, 1, 1, False, "still_listed")


def test_population_excludes_out_of_scope_federal(engine):
    assert "fed_out" not in spans(engine)


def test_daily_flow(engine):
    f = flow(engine)
    assert f == {
        ("commercial", 1): (2, 2, 0, False),
        ("commercial", 2): (3, 1, 0, True),
        ("commercial", 3): (2, 0, 1, True),
        ("commercial", 5): (2, 1, 0, False),
        ("commercial", 6): (4, 1, 2, True),
        ("commercial", 7): (3, 1, 1, True),
        ("commercial", 8): (2, 0, None, True),
        ("federal", 3): (1, 1, None, False),
    }


def test_flow_columns(engine):
    with engine.connect() as conn:
        cols = list(conn.execute(text("select * from v_daily_market_flow limit 0")).keys())
    assert cols == [
        "market",
        "snapshot_date",
        "jobs_seen",
        "jobs_first_seen",
        "jobs_last_seen",
        "prev_day_has_snapshot",
    ]
