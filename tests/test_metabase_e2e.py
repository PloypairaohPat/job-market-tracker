"""End-to-end: provision a REAL Metabase twice, then run every card.

Skipped unless METABASE_URL is set (CI skips it). Needs a running Metabase
(docker compose --profile bi up -d) reading a database loaded with
`seed_demo_data.py --full`, the reader role granted, and the METABASE_*
variables set (see docs/dashboard.md).
"""

import os

import pytest
import requests

from src.dashboard.provision import COLLECTION_NAME, Config, Provisioner
from src.dashboard.spec import load_dashboards

pytestmark = [
    pytest.mark.metabase,
    pytest.mark.skipif(not os.environ.get("METABASE_URL"), reason="METABASE_URL not set"),
]


def test_provision_twice_then_every_card_runs():
    config = Config.from_env()
    first = Provisioner(config).run()
    second = Provisioner(config).run()

    assert second.created == [] and second.updated == [] and second.deleted == []
    assert second.card_ids == first.card_ids and second.dashboard_ids == first.dashboard_ids

    spec = load_dashboards()
    n_cards = sum(1 for d in spec for c in d.cards if c.is_question)
    assert len(second.card_ids) == n_cards and len(second.dashboard_ids) == len(spec)

    session = requests.Session()
    token = session.post(
        f"{config.url}/api/session",
        json={"username": config.admin_email, "password": config.admin_password},
        timeout=30,
    ).json()["id"]
    session.headers["X-Metabase-Session"] = token

    # no duplicates in the collection
    (coll,) = [
        c
        for c in session.get(f"{config.url}/api/collection", timeout=30).json()
        if c.get("name") == COLLECTION_NAME and not c.get("archived")
    ]
    items = session.get(f"{config.url}/api/collection/{coll['id']}/items", timeout=30).json()[
        "data"
    ]
    cards = [i for i in items if i["model"] == "card"]
    dashboards = [i for i in items if i["model"] == "dashboard"]
    assert len(cards) == n_cards and len(dashboards) == len(spec)

    failures = {}
    for key, card_id in sorted(second.card_ids.items()):
        result = session.post(f"{config.url}/api/card/{card_id}/query", timeout=120).json()
        if result.get("status") != "completed" or result.get("error"):
            failures[key] = result.get("error") or result.get("status")
        elif config.is_demo and not result["data"]["rows"]:
            # demo data fills every card; real data may legitimately be empty
            # (e.g. visa cards before any LCA file is loaded)
            failures[key] = "no rows"
    assert failures == {}
