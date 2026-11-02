"""The daily runner waits for the database, and exits 2 if it never comes up.

The connect function and the sleep are fakes: nothing here waits for real,
and the "unreachable" database is never contacted.
"""

import os
import sys

import pytest
from sqlalchemy import create_engine

from src.pipeline import daily
from src.utils.config import Settings
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
FAKE_PASSWORD = "FAKEpw-0f1e2d"
DOWN_URL = f"postgresql+psycopg2://postgres:{FAKE_PASSWORD}@127.0.0.1:59999/nothing_test"
PING = "https://hc.example.com/ping/0f1e2d3c-fake-token"
EVERY_STEP = ("adzuna", "usajobs", "cleaning", "skills", "health")


class FakeConnect:
    """Refuses the first `failures` attempts (None = every attempt), with an
    error message that carries the password, then connects for real (or not)."""

    def __init__(self, failures=None, then=None):
        self.failures, self.then, self.calls = failures, then, 0

    def __call__(self, url):
        self.calls += 1
        if self.failures is None or self.calls <= self.failures:
            raise ConnectionRefusedError(
                f'connection to server at "127.0.0.1", port 59999 failed: Connection refused '
                f"(url {url}, password {FAKE_PASSWORD})\nIs the server running?"
            )
        if self.then:
            self.then(url)


class FakeSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


class FakePingSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return type("R", (), {"status_code": 200})()


# --------------------------------------------------------------------- #
# wait_for_database (unit)


def test_reachable_at_once_never_sleeps():
    connect, sleep = FakeConnect(failures=0), FakeSleep()
    assert daily.wait_for_database(DOWN_URL, 300, connect=connect, sleep=sleep) == (True, 0)
    assert (connect.calls, sleep.calls) == (1, [])


def test_reachable_on_the_third_attempt():
    connect, sleep = FakeConnect(failures=2), FakeSleep()
    assert daily.wait_for_database(DOWN_URL, 300, connect=connect, sleep=sleep) == (True, 20)
    assert connect.calls == 3
    assert sleep.calls == [daily.DB_WAIT_INTERVAL_SECONDS] * 2


def test_never_reachable_gives_up_after_the_wait():
    connect, sleep = FakeConnect(), FakeSleep()
    assert daily.wait_for_database(DOWN_URL, 25, connect=connect, sleep=sleep) == (False, 25)
    assert sleep.calls == [10, 10, 5]  # the last sleep is cut to the time left
    assert connect.calls == 4  # at 0, 10, 20 and 25 s


def test_db_wait_zero_is_one_attempt_and_no_sleep():
    connect, sleep = FakeConnect(), FakeSleep()
    assert daily.wait_for_database(DOWN_URL, 0, connect=connect, sleep=sleep) == (False, 0)
    assert (connect.calls, sleep.calls) == (1, [])


def test_attempts_are_logged_with_host_and_port_only(caplog):
    with caplog.at_level("INFO", logger="src.pipeline.daily"):
        daily.wait_for_database(DOWN_URL, 10, connect=FakeConnect(failures=1), sleep=FakeSleep())
    assert "database at 127.0.0.1:59999 not reachable (attempt 1, 0 s waited)" in caplog.text
    assert "database at 127.0.0.1:59999 reachable (attempt 2)" in caplog.text
    assert FAKE_PASSWORD not in caplog.text and DOWN_URL not in caplog.text
    assert "Is the server running?" not in caplog.text  # first line of the error only


# --------------------------------------------------------------------- #
# run_daily


def run_down(tmp_path, ping_url="", **kwargs):
    settings = Settings(database_url=DOWN_URL, healthcheck_ping_url=ping_url)
    return daily.run_daily(
        settings=settings,
        log_dir=tmp_path / "logs",
        candidates_out=tmp_path / "c.csv",
        db_connect=FakeConnect(),
        sleep=FakeSleep(),
        **kwargs,
    )


def test_never_reachable_exits_2_with_a_clear_message_and_no_password(tmp_path, capsys):
    session = FakePingSession()
    result = run_down(tmp_path, ping_url=PING, ping_session=session, db_wait=30)
    assert result.exit_code == daily.EXIT_DB_UNREACHABLE == 2
    assert [(s.name, s.ok, s.status) for s in result.steps] == [("db", False, "unreachable")]
    assert session.urls == [PING + "/fail"]

    message = (
        "database unreachable at 127.0.0.1:59999 after 30 s; is Docker Desktop running? "
        "Then: docker compose up -d db"
    )
    out = capsys.readouterr().out
    log = next((tmp_path / "logs").glob("daily-*.log")).read_text(encoding="utf-8")
    for text in (out, log):
        assert message in text
        assert "FAIL db" in text and "exit code 2" in text  # the one-screen summary
        assert FAKE_PASSWORD not in text and DOWN_URL not in text
        assert "0f1e2d3c-fake-token" not in text


def test_never_reachable_on_a_dry_run_sends_no_ping(tmp_path):
    session = FakePingSession()
    result = run_down(tmp_path, ping_url=PING, ping_session=session, dry_run=True, db_wait=0)
    assert result.exit_code == 2 and session.urls == []


def test_cli_passes_db_wait_and_exits_with_the_result_code(monkeypatch):
    seen = {}

    def fake_run_daily(skip, dry_run, db_wait):
        seen.update(skip=skip, dry_run=dry_run, db_wait=db_wait)
        return daily.DailyResult(exit_code=2)

    monkeypatch.setattr(daily, "run_daily", fake_run_daily)
    monkeypatch.setattr(sys, "argv", ["daily", "--db-wait", "0", "--skip", "adzuna"])
    with pytest.raises(SystemExit) as exit_:
        daily.main()
    assert exit_.value.code == 2
    assert seen == {"skip": ("adzuna",), "dry_run": False, "db_wait": 0}

    monkeypatch.setattr(sys, "argv", ["daily"])
    with pytest.raises(SystemExit):
        daily.main()
    assert seen["db_wait"] == daily.DB_WAIT_SECONDS == 300


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_a_database_that_comes_up_on_the_third_attempt_runs_normally(tmp_path):
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    engine.dispose()
    sleep = FakeSleep()
    result = daily.run_daily(
        skip=EVERY_STEP,
        settings=Settings(database_url=TEST_DB_URL),
        database_url=TEST_DB_URL,
        log_dir=tmp_path / "logs",
        candidates_out=tmp_path / "c.csv",
        db_connect=FakeConnect(failures=2, then=daily.try_connect),
        sleep=sleep,
    )
    assert result.exit_code == 0 and not result.locked_out
    assert [s.name for s in result.steps] == list(EVERY_STEP)  # no db line when it's up
    assert sleep.calls == [10, 10]
