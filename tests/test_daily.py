"""Integration tests for the daily runner (src/pipeline/daily.py).

Every API call goes to a fake HTTP session inside the real clients
(tests/pipeline_fakes.py); credentials are obviously fake.
"""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select, text

from src.models import IngestionRun, Job, JobSkill, JobSnapshot, JobVisaSignal
from src.pipeline import daily
from src.utils.config import Settings
from src.utils.db import session_scope
from tests.conftest import reset_schema
from tests.pipeline_fakes import RaisingHTTP, adzuna_client, usajobs_client

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]

FAKE_SECRETS = ("FAKEID", "FAKEKEY", "FAKEUSAJOBSKEY", "fake@example.com")


def settings(**overrides) -> Settings:
    values = {
        "database_url": TEST_DB_URL,
        "adzuna_app_id": "FAKEID",
        "adzuna_app_key": "FAKEKEY",
        "usajobs_api_key": "FAKEUSAJOBSKEY",
        "usajobs_user_agent_email": "fake@example.com",
    }
    values.update(overrides)
    return Settings(**values)


def ok_adzuna(settings, max_calls):
    return adzuna_client(max_calls=max_calls)


def failing_adzuna(settings, max_calls):
    return adzuna_client(http=RaisingHTTP(), max_calls=max_calls)


def ok_usajobs(settings, max_calls):
    return usajobs_client(max_calls=max_calls)


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def run(tmp_path, **kwargs):
    kwargs.setdefault("settings", settings())
    kwargs.setdefault("adzuna_client_factory", ok_adzuna)
    kwargs.setdefault("usajobs_client_factory", ok_usajobs)
    return daily.run_daily(
        database_url=TEST_DB_URL,
        log_dir=tmp_path / "logs",
        candidates_out=tmp_path / "candidates.csv",
        **kwargs,
    )


def count(model, *where) -> int:
    with session_scope(TEST_DB_URL) as session:
        return session.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


def runs_by_source() -> dict[str, list[str]]:
    with session_scope(TEST_DB_URL) as session:
        rows = session.execute(
            select(IngestionRun.source, IngestionRun.status).order_by(IngestionRun.id)
        ).all()
    out: dict[str, list[str]] = {}
    for source, status in rows:
        out.setdefault(source, []).append(status)
    return out


def test_full_run(db, tmp_path):
    result = run(tmp_path)
    assert result.exit_code == 0
    assert [(s.name, s.status) for s in result.steps] == [
        ("adzuna", "ok"),
        ("usajobs", "ok"),
        ("cleaning", "ok"),
        ("skills", "ok"),
    ]
    assert runs_by_source() == {"adzuna": ["ok"], "usajobs": ["ok"]}
    n_jobs = count(Job)
    assert n_jobs == 125  # 100 adzuna fixture jobs + 25 usajobs
    assert count(JobSnapshot) == n_jobs
    assert count(JobVisaSignal) == n_jobs  # cleaning ran over everything
    assert count(JobSkill) > 0

    log = (tmp_path / "logs" / f"daily-{datetime.now(UTC).date().isoformat()}.log").read_text(
        encoding="utf-8"
    )
    assert "step adzuna: start" in log and "step skills: end status=ok" in log
    assert "Daily run summary" in log
    assert not any(secret in log for secret in FAKE_SECRETS)


def test_second_run_same_day_is_idempotent(db, tmp_path):
    assert run(tmp_path).exit_code == 0
    snapshots, jobs = count(JobSnapshot), count(Job)
    assert run(tmp_path).exit_code == 0
    assert count(JobSnapshot) == snapshots  # (job_id, UTC date) upsert: no new rows
    assert count(Job) == jobs
    assert runs_by_source() == {"adzuna": ["ok", "ok"], "usajobs": ["ok", "ok"]}
    # the log file is appended, not replaced
    log = next((tmp_path / "logs").glob("daily-*.log")).read_text(encoding="utf-8")
    assert log.count("Daily run summary") == 2


def test_one_source_failing_does_not_stop_the_rest(db, tmp_path):
    result = run(tmp_path, adzuna_client_factory=failing_adzuna)
    assert result.exit_code == 1
    statuses = {s.name: s.status for s in result.steps}
    assert statuses == {"adzuna": "failed", "usajobs": "ok", "cleaning": "ok", "skills": "ok"}
    assert runs_by_source() == {"adzuna": ["failed"], "usajobs": ["ok"]}
    assert count(JobVisaSignal) == count(Job) == 25  # cleaning still ran on the usajobs jobs
    with session_scope(TEST_DB_URL) as session:
        error = session.execute(
            select(IngestionRun.error).where(IngestionRun.source == "adzuna")
        ).scalar_one()
    assert "FAKEKEY" not in error and "FAKEID" not in error
    log = next((tmp_path / "logs").glob("daily-*.log")).read_text(encoding="utf-8")
    assert not any(secret in log for secret in FAKE_SECRETS)


def test_missing_credentials_recorded_without_secret(db, tmp_path):
    result = run(tmp_path, settings=settings(adzuna_app_key="", usajobs_user_agent_email=""))
    assert result.exit_code == 1
    with session_scope(TEST_DB_URL) as session:
        rows = dict(session.execute(select(IngestionRun.source, IngestionRun.error)).all())
    assert rows["adzuna"] == "Missing required environment variable(s): ADZUNA_APP_KEY"
    assert rows["usajobs"] == "Missing required environment variable(s): USAJOBS_USER_AGENT_EMAIL"
    assert not any(secret in " ".join(rows.values()) for secret in FAKE_SECRETS)
    assert runs_by_source() == {"adzuna": ["failed"], "usajobs": ["failed"]}
    assert {s.name: s.ok for s in result.steps}["cleaning"] is True


def test_advisory_lock_blocks_a_concurrent_runner(db, tmp_path):
    engine = create_engine(TEST_DB_URL)
    holder = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        assert holder.execute(
            text("select pg_try_advisory_lock(:k)"), {"k": daily.DAILY_LOCK_KEY}
        ).scalar()
        result = run(tmp_path)
    finally:
        holder.execute(text("select pg_advisory_unlock(:k)"), {"k": daily.DAILY_LOCK_KEY})
        holder.close()
        engine.dispose()
    assert result.locked_out is True and result.exit_code == 0
    assert result.steps == []
    assert runs_by_source() == {}  # nothing ran
    assert run(tmp_path).exit_code == 0  # and the lock is free again afterwards


def test_skip_and_dry_run(db, tmp_path):
    result = run(tmp_path, skip=("adzuna", "skills"), dry_run=True)
    assert result.exit_code == 0
    assert [(s.name, s.status) for s in result.steps] == [
        ("adzuna", "skipped"),
        ("usajobs", "planned"),
        ("cleaning", "planned"),
        ("skills", "skipped"),
    ]
    assert runs_by_source() == {} and count(Job) == 0  # dry run: no calls, no writes
