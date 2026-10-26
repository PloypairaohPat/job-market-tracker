"""Provisioner unit tests against an in-memory fake Metabase (no network)."""

import logging
import sys

import pytest
import requests

from src.dashboard import provision
from src.dashboard.provision import (
    COLLECTION_NAME,
    DEMO_BANNER,
    Config,
    Provisioner,
    ProvisionError,
)
from src.dashboard.spec import load_dashboards
from tests.fake_metabase import FakeMetabase

ADMIN_PASSWORD = "demo-only-admin-pw"
READER_PASSWORD = "demo-only-reader-pw"

SPEC = load_dashboards()
N_CARDS = sum(1 for d in SPEC for c in d.cards if c.is_question)
N_DASHBOARDS = len(SPEC)


def config(db_name="jobmarket_demo") -> Config:
    return Config(
        url="http://metabase.invalid:3000",
        admin_email="fake@example.com",
        admin_password=ADMIN_PASSWORD,
        reader_password=READER_PASSWORD,
        db_host="db",
        db_name=db_name,
    )


def run(fake, **kwargs):
    return Provisioner(kwargs.pop("cfg", config()), session=fake, **kwargs).run()


def marked_items(fake, collection_id):
    cards = [c for c in fake.cards.values() if c["collection_id"] == collection_id]
    dashes = [d for d in fake.dashboards.values() if d["collection_id"] == collection_id]
    return cards, dashes


def our_collection(fake) -> int:
    (cid,) = [c["id"] for c in fake.collections.values() if c["name"] == COLLECTION_NAME]
    return cid


# --------------------------------------------------------------------- #


def test_first_run_sets_up_and_builds_everything():
    fake = FakeMetabase()
    result = run(fake)

    assert fake.setup_done and fake.admin == ("fake@example.com", ADMIN_PASSWORD)
    assert "setup" in result.created
    (db,) = fake.databases.values()
    assert db["name"] == "Job Market Tracker (jobmarket_demo)"
    assert db["details"]["user"] == "metabase_reader" and db["details"]["host"] == "db"
    assert ("POST", f"/api/database/{db['id']}/sync_schema") in fake.writes()

    cards, dashes = marked_items(fake, our_collection(fake))
    assert len(cards) == N_CARDS and len(dashes) == N_DASHBOARDS
    for card in cards:
        stage = card["dataset_query"]["stages"][0]
        assert card["dataset_query"]["lib/type"] == "mbql/query"
        assert stage["lib/type"] == "mbql.stage/native" and stage["native"].strip()
        assert "Defined in dashboards/sql/" in card["description"]
    # demo database -> every dashboard opens with the banner, everything else shifted down
    for dash in dashes:
        banner = [dc for dc in dash["dashcards"] if dc["row"] == 0]
        assert len(banner) == 1
        assert DEMO_BANNER in banner[0]["visualization_settings"]["text"]
        assert banner[0]["size_x"] == 24


def test_no_banner_on_a_real_database_name():
    fake = FakeMetabase()
    run(fake, cfg=config(db_name="jobmarket"))
    for dash in fake.dashboards.values():
        texts = [dc["visualization_settings"].get("text", "") for dc in dash["dashcards"]]
        assert not any(DEMO_BANNER in t for t in texts)


def test_second_run_changes_nothing():
    fake = FakeMetabase()
    first = run(fake)
    card_ids, dash_ids = dict(first.card_ids), dict(first.dashboard_ids)
    fake.calls.clear()

    second = run(fake)
    assert fake.content_writes() == []  # only login + schema sync
    assert second.created == second.updated == second.deleted == []
    assert second.card_ids == card_ids and second.dashboard_ids == dash_ids
    assert len(fake.cards) == N_CARDS and len(fake.dashboards) == N_DASHBOARDS


def test_spec_change_updates_in_place(monkeypatch):
    fake = FakeMetabase()
    first = run(fake)
    key = "market_jobs_by_market"
    fake.cards[first.card_ids[key]]["name"] = "renamed by hand in Metabase"
    fake.calls.clear()

    second = run(fake)
    assert f"card {key}" in second.updated
    assert ("PUT", f"/api/card/{first.card_ids[key]}") in fake.content_writes()
    assert second.card_ids[key] == first.card_ids[key]  # same id, no duplicate


def test_pruning_is_confined_to_the_collection():
    fake = FakeMetabase()
    run(fake)
    ours = our_collection(fake)
    other = fake.add_collection("Someone else's collection")
    stale = fake.add_card("old card", "x\n\nDefined in dashboards/sql/old_card.sql (...)", ours)
    outside = fake.add_card("lookalike", "Defined in dashboards/sql/old_card.sql", other)
    handmade = fake.add_card("hand-made question", "made in the UI", ours)
    dup_key = "health_window"
    duplicate = fake.add_card(
        "dup", f"Data window\n\nDefined in dashboards/sql/{dup_key}.sql (...)", ours
    )

    result = run(fake)
    assert stale not in fake.cards and duplicate not in fake.cards
    assert outside in fake.cards and handmade in fake.cards
    assert any("old_card" in d for d in result.deleted)
    assert len([d for d in result.deleted if d.startswith("card")]) == 2


def test_dry_run_makes_no_write_calls():
    fresh = FakeMetabase()
    result = Provisioner(config(), session=fresh, dry_run=True).run()
    assert fresh.writes() == [] and not fresh.setup_done
    assert "POST /api/setup" in result.planned

    built = FakeMetabase()
    run(built)
    built.cards[next(iter(built.cards))]["name"] = "drifted"
    built.calls.clear()
    result = Provisioner(config(), session=built, dry_run=True).run()
    assert built.content_writes() == []
    assert [w for w in built.writes() if w[0] != "POST" or "session" not in w[1]] == []
    assert any(p.startswith("PUT /api/card/") for p in result.planned)


def test_public_links_only_for_public_dashboards():
    fake = FakeMetabase()
    result = run(fake, public_links=True)
    assert fake.settings["enable-public-sharing"] is True
    by_slug = {slug: fake.dashboards[i] for slug, i in result.dashboard_ids.items()}
    assert by_slug["visa-outlook"]["public_uuid"] is None
    assert all(d["public_uuid"] for slug, d in by_slug.items() if slug != "visa-outlook")
    assert "visa-outlook" not in result.public_urls and len(result.public_urls) == 5

    # without the flag nothing is shared, and a private dashboard never keeps a link
    fake2 = FakeMetabase()
    r2 = run(fake2)
    assert fake2.settings["enable-public-sharing"] is False and r2.public_urls == {}
    fake2.dashboards[r2.dashboard_ids["visa-outlook"]]["public_uuid"] = "leaked"
    run(fake2)
    assert fake2.dashboards[r2.dashboard_ids["visa-outlook"]]["public_uuid"] is None


def test_no_password_in_logs_or_errors(caplog):
    caplog.set_level(logging.DEBUG)
    fake = FakeMetabase()
    fake.setup_error_body = f"invalid password {ADMIN_PASSWORD} for reader {READER_PASSWORD}"
    with pytest.raises(ProvisionError) as info:
        run(fake)
    assert ADMIN_PASSWORD not in str(info.value) and READER_PASSWORD not in str(info.value)
    assert "***" in str(info.value)

    ok = FakeMetabase()
    run(ok, public_links=True)
    logged = caplog.text
    assert ADMIN_PASSWORD not in logged and READER_PASSWORD not in logged
    assert "FAKESESSION" not in logged


def test_missing_settings_are_named():
    cfg = config()
    cfg.admin_password = ""
    with pytest.raises(ProvisionError, match="METABASE_ADMIN_PASSWORD"):
        Provisioner(cfg, session=FakeMetabase()).run()


class _Unreachable:
    headers: dict = {}

    def request(self, *args, **kwargs):
        raise requests.ConnectionError(f"refused; password={ADMIN_PASSWORD}")


def test_network_error_is_clear_and_exits_non_zero(monkeypatch, caplog):
    with pytest.raises(ProvisionError, match="cannot reach Metabase") as info:
        Provisioner(config(), session=_Unreachable()).run()
    assert ADMIN_PASSWORD not in str(info.value)

    monkeypatch.setattr(provision.requests, "Session", _Unreachable)
    for key, value in {
        "METABASE_URL": "http://metabase.invalid:3000",
        "METABASE_ADMIN_EMAIL": "fake@example.com",
        "METABASE_ADMIN_PASSWORD": ADMIN_PASSWORD,
        "METABASE_READER_PASSWORD": READER_PASSWORD,
        "METABASE_DB_NAME": "jobmarket_demo",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["provision"])
    with pytest.raises(SystemExit) as exit_info:
        provision.main()
    assert exit_info.value.code == 1
    assert ADMIN_PASSWORD not in caplog.text


def test_config_defaults_from_env():
    cfg = Config.from_env(
        {"DATABASE_URL": "postgresql+psycopg2://u:p@localhost:5432/jobmarket", "METABASE_URL": ""}
    )
    assert (cfg.db_host, cfg.db_port, cfg.db_name, cfg.db_user) == (
        "db",
        5432,
        "jobmarket",
        "metabase_reader",
    )
    assert cfg.url == "http://localhost:3000" and not cfg.is_demo


def test_public_links_use_the_site_url_when_set():
    cfg = config()
    cfg.site_url = "https://jobs.example.com"
    result = Provisioner(cfg, session=FakeMetabase(), public_links=True).run()
    assert result.public_urls and all(
        url.startswith("https://jobs.example.com/public/dashboard/")
        for url in result.public_urls.values()
    )
    env = {"METABASE_URL": "http://metabase:3000", "MB_SITE_URL": "https://jobs.example.com/"}
    assert Config.from_env(env).site_url == "https://jobs.example.com"
