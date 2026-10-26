"""Integration test: scripts/apply_views.py applies every view, idempotently."""

import os

import pytest
from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views, view_files
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


def test_apply_views_creates_every_view_and_reruns_cleanly():
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    expected = sorted(p.stem for p in view_files())

    first = apply_views(TEST_DB_URL)
    second = apply_views(TEST_DB_URL)  # CREATE OR REPLACE: must not fail on re-run

    assert first == second == [f"{name}.sql" for name in expected]
    with engine.connect() as conn:
        present = sorted(
            conn.execute(
                text("select table_name from information_schema.views where table_schema='public'")
            ).scalars()
        )
    engine.dispose()
    assert present == expected
