"""E0: scripts/bench_cleaning.py refuses unsafe databases and times every step."""

import os
import sys

import pytest

from scripts import bench_cleaning
from src.dashboard.demo_dataset import UnsafeDemoDatabaseError
from src.utils.db import dispose_engines

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg2://postgres:x@127.0.0.1:5432/jobmarket",
        "postgresql+psycopg2://postgres:x@db.example.invalid:5432/jobmarket_test",
    ],
)
def test_refuses_a_database_that_is_not_local_test_or_demo(url, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["bench", "--n", "10", "--database-url", url])
    with pytest.raises(UnsafeDemoDatabaseError):
        bench_cleaning.main()


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_times_and_counts_every_step(tmp_path):
    bench_cleaning.reset_schema(TEST_DB_URL)
    bench_cleaning.seed(TEST_DB_URL, 60)
    try:
        result = bench_cleaning.time_steps(TEST_DB_URL, tmp_path / "c.csv")
    finally:
        dispose_engines()
    assert list(result) == list(bench_cleaning.STEPS)
    assert all(r["seconds"] >= 0 and r["statements"] > 0 for r in result.values())
