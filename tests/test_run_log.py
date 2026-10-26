"""Run log (ingestion_runs) and secret redaction."""

import io
import logging
import os

import pytest
from sqlalchemy import create_engine, select

from src.ingestion import ingest_adzuna, ingest_usajobs
from src.ingestion.adzuna_client import AdzunaError
from src.ingestion.run_log import ERROR_MAX_CHARS, record_terminal_run, safe_error
from src.models import IngestionRun
from src.utils.db import session_scope
from src.utils.redaction import RedactingFilter, install_redaction, redact
from tests.conftest import reset_schema
from tests.pipeline_fakes import RaisingHTTP, adzuna_client, usajobs_client

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


# --------------------------------------------------------------------- #
# redaction (unit)


def test_redact_masks_secret_values_and_query_params():
    text = "GET /search/1?app_id=FAKEID&app_key=FAKEKEY&what=analyst failed for fake@example.com"
    out = redact(text, ["fake@example.com"])
    assert "FAKEID" not in out and "FAKEKEY" not in out and "fake@example.com" not in out
    assert "app_id=***&app_key=***&what=analyst" in out


def test_redact_ignores_empty_secrets_and_none():
    assert redact("nothing secret", ["", None]) == "nothing secret"
    assert redact(None, ["x"]) is None


def test_filter_redacts_messages_args_and_tracebacks():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    install_redaction(["FAKEUSAJOBSKEY"], handlers=[handler])
    log = logging.getLogger("test_redaction_filter")
    log.addHandler(handler)
    log.propagate = False
    try:
        log.warning("Request error: %s", "url?app_key=FAKEKEY")
        log.warning("header key FAKEUSAJOBSKEY leaked")
        try:
            raise RuntimeError("boom ?app_id=FAKEID&app_key=FAKEKEY")
        except RuntimeError:
            log.exception("failed")
    finally:
        log.removeHandler(handler)
    out = stream.getvalue()
    assert "FAKEKEY" not in out and "FAKEID" not in out and "FAKEUSAJOBSKEY" not in out
    assert "app_key=***" in out and "RuntimeError" in out


def test_safe_error_truncates():
    assert len(safe_error("x" * 5000)) == ERROR_MAX_CHARS
    assert isinstance(RedactingFilter(), logging.Filter)


# --------------------------------------------------------------------- #
# run log (integration)


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


def _runs():
    with session_scope(TEST_DB_URL) as session:
        return list(session.execute(select(IngestionRun).order_by(IngestionRun.id)).scalars())


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_ok_run_is_recorded_with_counts(db):
    client = adzuna_client()
    counts, stats = ingest_adzuna.run_logged(
        client, queries=["data analyst"], database_url=TEST_DB_URL
    )
    assert counts == {"data analyst": 100}

    (run,) = _runs()
    assert run.source == "adzuna" and run.status == "ok"
    assert run.finished_at is not None and run.finished_at >= run.started_at
    assert run.calls_made == 3  # page 1, page 2, empty page 3
    assert run.pages_fetched == 2
    assert run.jobs_processed == 100
    assert run.jobs_new == 100
    assert run.snapshot_date == run.started_at.date()
    assert run.params == {
        "queries": ["data analyst"],
        "max_pages": 5,
        "max_calls": 60,
        "dry_run": False,
    }
    assert run.error is None
    assert "FAKEKEY" not in str(run.params)

    # second run: same jobs, nothing new
    ingest_adzuna.run_logged(adzuna_client(), queries=["data analyst"], database_url=TEST_DB_URL)
    assert _runs()[1].jobs_new == 0


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_budget_cut_run_is_partial(db):
    client = adzuna_client(max_calls=1)
    counts, stats = ingest_adzuna.run_logged(
        client, queries=["data analyst", "senior data analyst"], database_url=TEST_DB_URL
    )
    assert stats.budget_cut is True
    assert counts == {"data analyst": 50}  # return value unchanged for existing callers
    (run,) = _runs()
    assert (run.status, run.calls_made, run.pages_fetched) == ("partial", 1, 1)


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_failed_run_stores_redacted_error_and_logs_no_secret(db):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    old_level = root.level
    root.setLevel(logging.INFO)
    install_redaction(["FAKEID", "FAKEKEY"], handlers=[handler])
    try:
        with pytest.raises(AdzunaError):
            ingest_adzuna.run_logged(
                adzuna_client(http=RaisingHTTP()),
                queries=["data analyst"],
                database_url=TEST_DB_URL,
            )
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)

    (run,) = _runs()
    assert run.status == "failed" and run.finished_at is not None
    assert run.calls_made == 1
    assert "Network error" in run.error and "app_key=***" in run.error
    assert "FAKEKEY" not in run.error and "FAKEID" not in run.error
    logged = stream.getvalue()
    assert "Request error" in logged
    assert "FAKEKEY" not in logged and "FAKEID" not in logged


def test_client_error_message_itself_is_redacted():
    """Even without a log filter, the raised error carries no credential."""
    with pytest.raises(AdzunaError) as info:
        adzuna_client(http=RaisingHTTP()).search("data analyst")
    assert "FAKEKEY" not in str(info.value) and info.value.__cause__ is None


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_terminal_runs_skipped_and_failed(db):
    record_terminal_run(
        "adzuna", "skipped_budget", {"max_calls": 0}, "used 975 of 1000", database_url=TEST_DB_URL
    )
    record_terminal_run(
        "usajobs",
        "failed",
        {},
        "Missing required environment variable 'USAJOBS_API_KEY'",
        secrets=["FAKEUSAJOBSKEY"],
        database_url=TEST_DB_URL,
    )
    skipped, failed = _runs()
    assert (skipped.status, skipped.calls_made, skipped.finished_at is not None) == (
        "skipped_budget",
        0,
        True,
    )
    assert failed.status == "failed" and "USAJOBS_API_KEY" in failed.error


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_usajobs_run_is_recorded(db):
    counts, _ = ingest_usajobs.run_logged(
        usajobs_client(), queries=["data analyst"], series_codes=["1560"], database_url=TEST_DB_URL
    )
    (run,) = _runs()
    assert run.source == "usajobs" and run.status == "ok"
    assert run.jobs_new == 25 and run.pages_fetched == 2  # same fixture page for both searches
    assert run.params["series_codes"] == ["1560"]


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_dry_run_writes_no_run_row(db):
    ingest_adzuna.run_ingestion(
        adzuna_client(), queries=["data analyst"], dry_run=True, database_url=TEST_DB_URL
    )
    assert _runs() == []
