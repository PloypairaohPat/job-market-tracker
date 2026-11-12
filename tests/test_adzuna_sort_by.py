"""D2: the optional ADZUNA_SORT_BY setting.

Unset, every request and every stored params dict is exactly what it was
before the setting existed. Set, the value is sent as Adzuna's sort_by and
recorded in raw_responses.params and ingestion_runs.params.
"""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select

from src.ingestion import ingest_adzuna
from src.models import IngestionRun, RawResponse
from src.utils.config import Settings, get_settings
from src.utils.db import session_scope
from tests.conftest import reset_schema
from tests.pipeline_fakes import FakeAdzunaHTTP, adzuna_client

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")

# What the client sent before ADZUNA_SORT_BY existed (adzuna_client.search).
BEFORE = {
    "app_id": "FAKEID",
    "app_key": "FAKEKEY",
    "what": "data analyst",
    "results_per_page": 50,
    "content-type": "application/json",
}


class RecordingHTTP(FakeAdzunaHTTP):
    def __init__(self):
        super().__init__()
        self.params: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.params.append(dict(params))
        return super().get(url, params=params, timeout=timeout)


def test_setting_is_unset_by_default(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://x@127.0.0.1/x_test")
    monkeypatch.delenv("ADZUNA_SORT_BY", raising=False)
    assert get_settings().adzuna_sort_by == ""
    monkeypatch.setenv("ADZUNA_SORT_BY", "  date ")
    assert get_settings().adzuna_sort_by == "date"


def test_unset_sends_exactly_the_old_request_parameters():
    http = RecordingHTTP()
    ingest_adzuna.run_ingestion(
        adzuna_client(http), queries=["data analyst"], dry_run=True, sort_by=None
    )
    assert http.params and all(p == BEFORE for p in http.params)


def test_empty_string_is_unset():
    http = RecordingHTTP()
    ingest_adzuna.run_ingestion(
        adzuna_client(http), queries=["data analyst"], dry_run=True, sort_by=""
    )
    assert all(p == BEFORE for p in http.params)


def test_set_sends_sort_by_on_every_page():
    http = RecordingHTTP()
    ingest_adzuna.run_ingestion(
        adzuna_client(http), queries=["data analyst"], dry_run=True, sort_by="date"
    )
    assert len(http.params) >= 2
    assert all(p == {**BEFORE, "sort_by": "date"} for p in http.params)


# --------------------------------------------------------------------- #
# what gets stored


@pytest.fixture()
def db():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    yield engine
    engine.dispose()


def stored_params():
    with session_scope(TEST_DB_URL) as s:
        raw = [r.params for r in s.execute(select(RawResponse)).scalars()]
        runs = [r.params for r in s.execute(select(IngestionRun)).scalars()]
    return raw, runs


def guarded(sort_by, http):
    return ingest_adzuna.run_guarded(
        Settings(database_url=TEST_DB_URL, adzuna_sort_by=sort_by),
        max_calls=60,
        queries=["data analyst"],
        database_url=TEST_DB_URL,
        now=datetime(2026, 10, 5, 12, tzinfo=UTC),
        client_factory=lambda settings, max_calls: adzuna_client(http, max_calls=max_calls),
    )


@needs_db
@pytest.mark.integration
def test_unset_stores_the_old_params(db):
    http = RecordingHTTP()
    status, _, _ = guarded("", http)
    assert status == "ok"
    raw, runs = stored_params()
    assert raw == [{"what": "data analyst", "page": 1}, {"what": "data analyst", "page": 2}]
    assert len(runs) == 1 and "sort_by" not in runs[0]
    assert all("sort_by" not in p for p in http.params)


@needs_db
@pytest.mark.integration
def test_set_is_recorded_on_every_page_and_the_run(db):
    http = RecordingHTTP()
    status, _, _ = guarded("date", http)
    assert status == "ok"
    raw, runs = stored_params()
    assert raw == [
        {"what": "data analyst", "page": 1, "sort_by": "date"},
        {"what": "data analyst", "page": 2, "sort_by": "date"},
    ]
    assert runs[0]["sort_by"] == "date"
    assert all(p["sort_by"] == "date" for p in http.params)


def test_smoke_script_sends_sort_by_only_when_asked(monkeypatch, capsys):
    from scripts import smoke_adzuna

    sent = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def search(self, query, results_per_page=10, **filters):
            sent.append(filters)
            return {"count": 3, "mean": 0, "results": []}

    monkeypatch.setattr(smoke_adzuna, "AdzunaClient", Client)
    monkeypatch.setattr(
        smoke_adzuna,
        "get_settings",
        lambda require_adzuna: Settings(database_url="x", adzuna_app_id="a", adzuna_app_key="b"),
    )
    smoke_adzuna.main([])
    smoke_adzuna.main(["--sort-by", "date"])
    assert sent == [{}, {"sort_by": "date"}]
    assert "sort_by='date'" in capsys.readouterr().out
