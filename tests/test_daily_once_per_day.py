"""--once-per-day: the daily runner is safe to trigger several times a day.

A fixed `now`, seeded ingestion_runs rows, and client factories that fail
the test if a source that should be skipped is ever built. The sources
that do run use the fixture-backed fake clients (tests/pipeline_fakes.py):
no network.
"""

import os
import sys
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select

from src.models import IngestionRun
from src.pipeline import daily
from src.utils.config import Settings
from src.utils.db import session_scope
from tests.conftest import reset_schema
from tests.pipeline_fakes import adzuna_client, usajobs_client

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
TODAY = NOW.date()
PING = "https://hc.example.com/ping/0f1e2d3c-fake-token"
REASON = f"--once-per-day: already ran for {TODAY}"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


class Factory:
    """A client factory that records each build, or refuses to be built."""

    def __init__(self, make=None):
        self.make, self.calls = make, 0

    def __call__(self, settings, max_calls):
        self.calls += 1
        if self.make is None:
            raise AssertionError("this source must not run: no client may be built")
        return self.make(max_calls=max_calls)


class FakePingSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return type("R", (), {"status_code": 200})()


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def seed_run(source, status, day=TODAY):
    finished = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=11)
    with session_scope(TEST_DB_URL) as session:
        session.add(
            IngestionRun(
                source=source,
                started_at=finished - timedelta(minutes=5),
                finished_at=finished,
                status=status,
                calls_made=0,
                snapshot_date=day,
                params={},
            )
        )


def n_runs() -> int:
    with session_scope(TEST_DB_URL) as session:
        return session.execute(select(func.count()).select_from(IngestionRun)).scalar_one()


def run(tmp_path, adzuna=None, usajobs=None, **kwargs):
    settings = Settings(
        database_url=TEST_DB_URL,
        adzuna_app_id="FAKEID",
        adzuna_app_key="FAKEKEY",
        usajobs_api_key="FAKEUSAJOBSKEY",
        usajobs_user_agent_email="fake@example.com",
        healthcheck_ping_url=PING,
    )
    kwargs.setdefault("once_per_day", True)
    return daily.run_daily(
        settings=settings,
        database_url=TEST_DB_URL,
        now=NOW,
        log_dir=tmp_path / "logs",
        candidates_out=tmp_path / "c.csv",
        adzuna_client_factory=adzuna or Factory(),
        usajobs_client_factory=usajobs or Factory(),
        **kwargs,
    )


def log_text(tmp_path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "logs").glob("*.log"))


def statuses(result) -> dict[str, str]:
    return {s.name: s.status for s in result.steps}


# --------------------------------------------------------------------- #


def test_both_sources_done_today_does_nothing(db, tmp_path):
    seed_run("adzuna", "ok")
    seed_run("usajobs", "partial")  # partial counts as done
    ping = FakePingSession()
    result = run(tmp_path, ping_session=ping)  # factories refuse to build a client

    assert result.exit_code == 0 and result.already_ran
    assert statuses(result) == {name: "skipped" for name in daily.STEPS}
    assert {s.detail for s in result.steps} == {REASON}
    assert n_runs() == 2  # nothing recorded
    assert ping.urls == []  # no ping either: nothing ran
    log = log_text(tmp_path)
    assert f"already ran for {TODAY}; nothing to do" in log
    assert "Daily run summary" in log and "exit code 0" in log
    assert "step adzuna: start" not in log and "step health: start" not in log


def test_one_source_done_runs_only_the_other_then_the_rest(db, tmp_path):
    seed_run("adzuna", "ok")
    usajobs = Factory(usajobs_client)
    result = run(tmp_path, usajobs=usajobs)  # the adzuna factory refuses

    got = statuses(result)
    assert got["adzuna"] == "skipped" and result.steps[0].detail == REASON
    assert (got["usajobs"], got["cleaning"], got["skills"]) == ("ok", "ok", "ok")
    assert got["health"] != "skipped"  # health always runs after work was done
    assert usajobs.calls == 1 and not result.already_ran
    with session_scope(TEST_DB_URL) as session:
        sources = sorted(session.execute(select(IngestionRun.source)).scalars())
    assert sources == ["adzuna", "usajobs"]  # only usajobs recorded a new run
    assert f"adzuna already ran for {TODAY}; running the rest" in log_text(tmp_path)


def test_the_other_source_done_is_symmetric(db, tmp_path):
    seed_run("usajobs", "ok")
    adzuna = Factory(adzuna_client)
    result = run(tmp_path, adzuna=adzuna, skip=("cleaning", "skills", "health"))
    got = statuses(result)
    assert (got["adzuna"], got["usajobs"]) == ("ok", "skipped")
    assert adzuna.calls == 1


def test_neither_done_runs_normally_and_only_ok_or_partial_today_counts(db, tmp_path):
    seed_run("adzuna", "failed")  # today, but failed: retry it
    seed_run("adzuna", "skipped_budget")  # today, but no data: retry it
    seed_run("usajobs", "ok", day=TODAY - timedelta(days=1))  # yesterday: doesn't count
    adzuna, usajobs = Factory(adzuna_client), Factory(usajobs_client)
    result = run(tmp_path, adzuna=adzuna, usajobs=usajobs)

    got = statuses(result)
    assert (got["adzuna"], got["usajobs"], got["cleaning"], got["skills"]) == ("ok",) * 4
    assert (adzuna.calls, usajobs.calls) == (1, 1)
    assert "already ran" not in log_text(tmp_path)


def test_without_the_flag_a_second_run_still_runs(db, tmp_path):
    seed_run("adzuna", "ok")
    seed_run("usajobs", "ok")
    usajobs = Factory(usajobs_client)
    result = run(
        tmp_path,
        usajobs=usajobs,
        once_per_day=False,
        skip=("adzuna", "cleaning", "skills", "health"),
    )
    assert statuses(result)["usajobs"] == "ok" and usajobs.calls == 1


def test_user_skips_and_once_per_day_combine(db, tmp_path):
    seed_run("adzuna", "ok")
    result = run(tmp_path, skip=("usajobs", "skills"))
    got = statuses(result)
    assert got == {
        "adzuna": "skipped",
        "usajobs": "skipped",
        "cleaning": "ok",
        "skills": "skipped",
        "health": got["health"],
    }
    details = {s.name: s.detail for s in result.steps}
    assert details["adzuna"] == REASON and details["usajobs"] == "--skip"


# --------------------------------------------------------------------- #
# dry runs: the check reads ingestion_runs; nothing is written or called


def test_dry_run_with_both_done_does_nothing(db, tmp_path):
    seed_run("adzuna", "ok")
    seed_run("usajobs", "ok")
    result = run(tmp_path, dry_run=True)
    assert result.exit_code == 0 and result.already_ran
    assert n_runs() == 2


def test_dry_run_with_one_done_plans_only_the_other(db, tmp_path):
    seed_run("usajobs", "ok")
    result = run(tmp_path, dry_run=True)  # neither factory may be built on a dry run
    got = statuses(result)
    assert got["usajobs"] == "skipped"
    assert (got["adzuna"], got["cleaning"], got["skills"]) == ("planned",) * 3
    assert n_runs() == 1  # the dry run wrote no run row


def test_dry_run_with_neither_done_plans_everything(db, tmp_path):
    result = run(tmp_path, dry_run=True)
    got = statuses(result)
    assert (got["adzuna"], got["usajobs"], got["cleaning"], got["skills"]) == ("planned",) * 4
    assert n_runs() == 0


# --------------------------------------------------------------------- #


def test_cli_flag(monkeypatch):
    seen = {}

    def fake_run_daily(skip, dry_run, db_wait, once_per_day):
        seen.update(skip=skip, once_per_day=once_per_day)
        return daily.DailyResult(exit_code=0)

    monkeypatch.setattr(daily, "run_daily", fake_run_daily)
    for argv, expected in ((["daily", "--once-per-day"], True), (["daily"], False)):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exit_:
            daily.main()
        assert exit_.value.code == 0 and seen["once_per_day"] is expected
