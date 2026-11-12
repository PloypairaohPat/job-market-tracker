"""A1: one engine (and pool) per database URL in src.utils.db."""

import os

import pytest
from sqlalchemy import create_engine, text

import src.utils.db as dbmod

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _clean_cache():
    dbmod.dispose_engines()
    yield
    dbmod.dispose_engines()


@pytest.fixture()
def counting_create_engine(monkeypatch):
    calls = []

    def fake(url, **kwargs):
        calls.append(str(url))
        # sqlite in memory: a real Engine, no server needed
        return create_engine("sqlite://")

    monkeypatch.setattr(dbmod, "create_engine", fake)
    return calls


def test_same_url_reuses_one_engine(counting_create_engine):
    url = "postgresql+psycopg2://u:p@127.0.0.1:5432/a_test"
    for _ in range(3):
        with dbmod.session_scope(url):
            pass
    assert counting_create_engine == [url]
    assert dbmod.get_engine(url) is dbmod.get_engine(url)


def test_two_urls_make_two_engines(counting_create_engine):
    a = "postgresql+psycopg2://u:p@127.0.0.1:5432/a_test"
    b = "postgresql+psycopg2://u:p@127.0.0.1:5432/b_test"
    ea, eb = dbmod.get_engine(a), dbmod.get_engine(b)
    assert ea is not eb
    dbmod.get_engine(a)
    assert counting_create_engine == [a, b]


def test_none_resolves_to_settings_url_after_explicit_url(counting_create_engine, monkeypatch):
    settings_url = "postgresql+psycopg2://u:p@127.0.0.1:5432/settings_test"

    class FakeSettings:
        database_url = settings_url

    monkeypatch.setattr(dbmod, "get_settings", lambda: FakeSettings())
    explicit = "postgresql+psycopg2://u:p@127.0.0.1:5432/explicit_test"
    e_explicit = dbmod.get_engine(explicit)
    e_default = dbmod.get_engine(None)
    assert e_default is not e_explicit
    assert counting_create_engine == [explicit, settings_url]
    assert dbmod.get_engine() is e_default


def test_dispose_engines_forgets_and_counts(counting_create_engine):
    url = "postgresql+psycopg2://u:p@127.0.0.1:5432/a_test"
    dbmod.get_engine(url)
    assert dbmod.dispose_engines() == 1
    assert dbmod.dispose_engines() == 0
    dbmod.get_engine(url)
    assert counting_create_engine == [url, url]


def test_legacy_globals_reset_is_harmless(counting_create_engine):
    url = "postgresql+psycopg2://u:p@127.0.0.1:5432/a_test"
    e1 = dbmod.get_engine(url)
    dbmod._engine = None
    dbmod._SessionFactory = None
    with dbmod.session_scope(url):
        pass
    assert dbmod.get_engine(url) is e1
    assert counting_create_engine == [url]


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_commit_on_success_and_rollback_on_error():
    with dbmod.session_scope(TEST_DB_URL) as s:
        s.execute(text("drop table if exists a1_scope_probe"))
        s.execute(text("create table a1_scope_probe (n int)"))
    with dbmod.session_scope(TEST_DB_URL) as s:
        s.execute(text("insert into a1_scope_probe values (1)"))
    with pytest.raises(RuntimeError), dbmod.session_scope(TEST_DB_URL) as s:
        s.execute(text("insert into a1_scope_probe values (2)"))
        raise RuntimeError("boom")
    with dbmod.session_scope(TEST_DB_URL) as s:
        rows = s.execute(text("select n from a1_scope_probe order by n")).scalars().all()
        s.execute(text("drop table a1_scope_probe"))
    assert rows == [1]
