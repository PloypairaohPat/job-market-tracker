"""The optional dead-man's-switch ping at the end of a daily run."""

import io
import logging
import os

import pytest
import requests
from sqlalchemy import create_engine

from src.pipeline import daily
from src.utils.config import Settings
from src.utils.redaction import RedactingFilter, url_secrets
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
PING = "https://hc.example.com/ping/0f1e2d3c-fake-token"
EVERY_STEP = ("adzuna", "usajobs", "cleaning", "skills", "health")


class FakePingSession:
    def __init__(self, status=200, exc=None):
        self.status, self.exc, self.urls = status, exc, []

    def get(self, url, timeout=None):
        self.urls.append((url, timeout))
        if self.exc:
            raise self.exc
        return type("R", (), {"status_code": self.status})()


# --------------------------------------------------------------------- #
# send_ping (unit)


def test_success_and_fail_urls_and_timeout():
    s = FakePingSession()
    assert daily.send_ping(PING, True, s) is True
    assert daily.send_ping(PING + "/", False, s) is True
    assert s.urls == [
        (PING, daily.PING_TIMEOUT_SECONDS),
        (PING + "/fail", daily.PING_TIMEOUT_SECONDS),
    ]
    assert daily.PING_TIMEOUT_SECONDS <= 10


def test_a_failed_ping_never_raises():
    assert daily.send_ping(PING, True, FakePingSession(status=500)) is False
    exc = requests.ConnectionError("Max retries exceeded")
    assert daily.send_ping(PING, True, FakePingSession(exc=exc)) is False


def test_ping_url_and_its_token_are_masked():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter(url_secrets(PING)))
    daily.logger.addHandler(handler)
    try:
        # the way requests really reports it: host and path apart
        exc = requests.ConnectionError(
            "HTTPSConnectionPool(host='hc.example.com', port=443): Max retries exceeded "
            "with url: /ping/0f1e2d3c-fake-token/fail (Caused by NameResolutionError)"
        )
        daily.send_ping(PING, False, FakePingSession(exc=exc))
    finally:
        daily.logger.removeHandler(handler)
    out = stream.getvalue()
    assert "ping (fail) failed" in out
    assert "0f1e2d3c-fake-token" not in out and PING not in out


# --------------------------------------------------------------------- #
# run_daily (integration: the run log needs a database)

needs_db = pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def run(tmp_path, ping_url, session, **kwargs):
    settings = Settings(database_url=TEST_DB_URL, healthcheck_ping_url=ping_url)
    return daily.run_daily(
        database_url=TEST_DB_URL,
        settings=settings,
        log_dir=tmp_path / "logs",
        candidates_out=tmp_path / "c.csv",
        ping_session=session,
        **kwargs,
    )


def log_text(tmp_path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "logs").glob("*.log"))


@pytest.mark.integration
@needs_db
def test_not_configured_sends_nothing(db, tmp_path):
    s = FakePingSession()
    assert run(tmp_path, "", s, skip=EVERY_STEP).exit_code == 0
    assert s.urls == []


@pytest.mark.integration
@needs_db
def test_success_pings_the_url(db, tmp_path):
    s = FakePingSession()
    assert run(tmp_path, PING, s, skip=EVERY_STEP).exit_code == 0
    assert [u for u, _ in s.urls] == [PING]


@pytest.mark.integration
@needs_db
def test_failure_pings_fail_and_keeps_exit_code(db, tmp_path):
    s = FakePingSession()
    # no Adzuna credentials -> the adzuna step fails -> exit 1
    result = run(tmp_path, PING, s, skip=("usajobs", "cleaning", "skills", "health"))
    assert result.exit_code == 1
    assert [u for u, _ in s.urls] == [PING + "/fail"]


@pytest.mark.integration
@needs_db
@pytest.mark.parametrize("status,exc", [(500, None), (200, requests.Timeout("timed out"))])
def test_a_broken_ping_never_changes_the_exit_code(db, tmp_path, status, exc):
    ok = run(tmp_path, PING, FakePingSession(status=status, exc=exc), skip=EVERY_STEP)
    assert ok.exit_code == 0
    bad = run(
        tmp_path,
        PING,
        FakePingSession(status=status, exc=exc),
        skip=("usajobs", "cleaning", "skills", "health"),
    )
    assert bad.exit_code == 1
    text = log_text(tmp_path)
    assert "dead-man's-switch ping" in text
    assert PING not in text and "0f1e2d3c-fake-token" not in text


@pytest.mark.integration
@needs_db
def test_no_ping_on_dry_run(db, tmp_path):
    s = FakePingSession()
    run(tmp_path, PING, s, skip=EVERY_STEP, dry_run=True)
    assert s.urls == []


@pytest.mark.integration
@needs_db
def test_masked_in_the_daily_log_on_a_real_connection_error(db, tmp_path):
    exc = requests.ConnectionError(
        "HTTPSConnectionPool(host='hc.example.com', port=443): Max retries exceeded "
        "with url: /ping/0f1e2d3c-fake-token (Caused by NameResolutionError)"
    )
    assert run(tmp_path, PING, FakePingSession(exc=exc), skip=EVERY_STEP).exit_code == 0
    text = log_text(tmp_path)
    assert "ping (success) failed" in text
    assert "0f1e2d3c-fake-token" not in text and "hc.example.com/ping" not in text
