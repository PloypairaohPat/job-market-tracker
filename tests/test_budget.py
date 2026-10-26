"""Monthly Adzuna budget guard (src/ingestion/budget.py) with a fixed `now`."""

import os
import sys
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select

from src.ingestion import ingest_adzuna
from src.ingestion.budget import (
    adzuna_calls_used,
    days_left_in_month,
    month_bounds,
    plan_adzuna_run,
)
from src.models import IngestionRun, RawResponse
from src.utils.config import Settings
from src.utils.db import session_scope
from tests.conftest import reset_schema
from tests.pipeline_fakes import adzuna_client

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


def at(day: int, month: int = 10, year: int = 2026, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


# --------------------------------------------------------------------- #
# calendar arithmetic (unit)


def test_days_left_includes_today():
    assert days_left_in_month(at(1)) == 31
    assert days_left_in_month(at(15)) == 17
    assert days_left_in_month(at(31)) == 1
    assert days_left_in_month(at(1, month=2)) == 28


def test_month_bounds_and_december_rollover():
    assert month_bounds(at(15)) == (at(1, hour=0), at(1, month=11, hour=0))
    assert month_bounds(at(31, month=12)) == (
        at(1, month=12, hour=0),
        at(1, month=1, year=2027, hour=0),
    )


# --------------------------------------------------------------------- #
# integration


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def seed_runs(*runs: tuple[datetime, int], source: str = "adzuna") -> None:
    with session_scope(TEST_DB_URL) as session:
        for started, calls in runs:
            session.add(
                IngestionRun(
                    source=source,
                    started_at=started,
                    finished_at=started + timedelta(minutes=5),
                    status="ok",
                    calls_made=calls,
                    snapshot_date=started.date(),
                    params={},
                )
            )


def seed_raw(n: int, fetched_at: datetime, source: str = "adzuna") -> None:
    with session_scope(TEST_DB_URL) as session:
        for _ in range(n):
            session.add(
                RawResponse(
                    source=source, endpoint="/x", params={}, response={}, fetched_at=fetched_at
                )
            )


def plan(now, max_calls=30, budget=1000, reserve=25):
    with session_scope(TEST_DB_URL) as session:
        return plan_adzuna_run(session, now, max_calls=max_calls, budget=budget, reserve=reserve)


needs_db = pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")


@needs_db
@pytest.mark.integration
def test_day_one_empty_month_is_never_throttled(db):
    d = plan(at(1), max_calls=60)
    assert (d.used, d.days_left, d.cap) == (0, 31, 31)  # (1000 - 0 - 25) // 31
    assert plan(at(1), max_calls=30).cap == 30


@needs_db
@pytest.mark.integration
def test_mid_month_normal(db):
    seed_runs(*[(at(day, hour=7), 30) for day in range(1, 15)])  # 14 days x 30 = 420
    d = plan(at(15))
    assert d.used == 420 and d.days_left == 17
    assert d.cap == 30  # min(30, (1000 - 420 - 25) // 17 = 32)


@needs_db
@pytest.mark.integration
def test_last_day_of_month(db):
    seed_runs((at(5), 900))
    assert plan(at(31), max_calls=60).cap == 60  # (1000 - 900 - 25) // 1 = 75
    seed_runs((at(30), 60))
    assert plan(at(31), max_calls=60).cap == 15  # 1000 - 960 - 25


@needs_db
@pytest.mark.integration
def test_exhausted_budget_records_skipped_and_builds_no_client(db):
    seed_runs((at(3), 980))

    def must_not_build(settings, max_calls):
        raise AssertionError("no client may be built when the budget is exhausted")

    status, counts, decision = ingest_adzuna.run_guarded(
        Settings(database_url=TEST_DB_URL),
        max_calls=30,
        database_url=TEST_DB_URL,
        now=at(20),
        client_factory=must_not_build,
    )
    assert status == "skipped_budget" and counts == {} and decision.cap <= 0
    with session_scope(TEST_DB_URL) as session:
        skipped = session.execute(
            select(IngestionRun).where(IngestionRun.status == "skipped_budget")
        ).scalar_one()
    assert skipped.calls_made == 0 and "used 980 of 1000" in skipped.error


@needs_db
@pytest.mark.integration
def test_history_counted_from_raw_responses(db):
    seed_raw(50, at(2))  # pages fetched before the run log existed
    assert plan(at(10)).used == 50
    seed_runs((at(9), 30))
    assert plan(at(10)).used == 50  # larger of runs (30) and raw (50)
    seed_runs((at(9, hour=8), 40))
    assert plan(at(10)).used == 70  # runs (70) now exceed raw (50)


@needs_db
@pytest.mark.integration
def test_month_rollover_resets_the_count(db):
    seed_runs((at(30, hour=7), 900))
    seed_raw(20, at(30, hour=7))
    seed_runs((at(1, month=11, hour=7), 0), source="usajobs")  # other sources never count
    with session_scope(TEST_DB_URL) as session:
        assert adzuna_calls_used(session, at(31)) == 900
        assert adzuna_calls_used(session, at(1, month=11)) == 0
    assert plan(at(1, month=11)).cap == 30


@needs_db
@pytest.mark.integration
def test_guarded_run_caps_the_client(db):
    seed_runs((at(5), 960))
    built = {}

    def factory(settings, max_calls):
        built["max_calls"] = max_calls
        return adzuna_client(max_calls=max_calls)

    status, counts, decision = ingest_adzuna.run_guarded(
        Settings(database_url=TEST_DB_URL),
        max_calls=60,
        queries=["data analyst"],
        database_url=TEST_DB_URL,
        now=at(31),
        client_factory=factory,
    )
    assert built["max_calls"] == decision.cap == 15
    assert status == "ok"
    with session_scope(TEST_DB_URL) as session:
        run = session.execute(
            select(IngestionRun).where(IngestionRun.status == "ok", IngestionRun.calls_made == 3)
        ).scalar_one()
    assert run.params["max_calls"] == 15 and run.params["requested_max_calls"] == 60


@needs_db
@pytest.mark.integration
def test_ingest_adzuna_main_uses_the_guard(db, monkeypatch):
    """main() with an exhausted month skips cleanly (no client, exit 0)."""
    seed_runs((datetime.now(UTC), 1000))
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    monkeypatch.setenv("ADZUNA_APP_ID", "FAKEID")
    monkeypatch.setenv("ADZUNA_APP_KEY", "FAKEKEY")
    monkeypatch.setattr(sys, "argv", ["ingest_adzuna"])

    def must_not_build(settings, max_calls):
        raise AssertionError("main() built a client despite an exhausted budget")

    monkeypatch.setattr(ingest_adzuna, "build_client", must_not_build)
    ingest_adzuna.main()  # returns normally: skipped_budget is not an error
    with session_scope(TEST_DB_URL) as session:
        statuses = list(session.execute(select(IngestionRun.status)).scalars())
    assert statuses.count("skipped_budget") == 1
