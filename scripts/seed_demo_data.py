"""Seed the database with synthetic demo data — no API key required.

Usage:  python scripts/seed_demo_data.py          # default: Adzuna fixture jobs
        python scripts/seed_demo_data.py --full   # full dashboard demo dataset

Default mode loads the synthetic fixture pages from tests/fixtures/ through
the real ingestion pipeline, so anyone cloning the repo can exercise the
full stack (schema, upserts, notebook) before registering for Adzuna
credentials. Demo rows are ordinary rows; wipe with `alembic downgrade
base && alembic upgrade head` before real ingestion if you want a clean
dataset.

`--full` builds the dashboard demo dataset (src/dashboard/demo_dataset.py):
both markets, four weeks of snapshot history with one missing day, a run
log, FAKE employers with LCA rows and every visa bucket. It TRUNCATES the
target database first, so it refuses anything but a local database whose
name contains "demo" or "test". Part of it is written directly with SQL
-- it is demo data, not pipeline output.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python scripts/x.py`

from sqlalchemy import create_engine, text

from scripts.apply_views import apply_views
from src.dashboard.demo_dataset import FixtureClient, build_full_demo
from src.ingestion.ingest_adzuna import TARGET_QUERIES, run_ingestion, summarize
from src.utils.config import get_settings


def view_row_counts(database_url: str) -> dict[str, int]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            views = conn.execute(
                text(
                    "select viewname from pg_views where schemaname = 'public' "
                    "and viewname like 'v\\_%' order by viewname"
                )
            ).scalars()
            return {
                v: conn.execute(text(f'select count(*) from "{v}"')).scalar_one() for v in views
            }
    finally:
        engine.dispose()


def seed_full(database_url: str, **kwargs) -> dict[str, int]:
    """Build the full demo dataset, apply the views, return per-view row counts."""
    build_full_demo(database_url, **kwargs)
    apply_views(database_url)
    return view_row_counts(database_url)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argp = argparse.ArgumentParser(description="Seed synthetic demo data (no API key needed).")
    argp.add_argument(
        "--full",
        action="store_true",
        help="full dashboard demo dataset; TRUNCATES the target (local demo/test DB only)",
    )
    args = argp.parse_args()

    if args.full:
        counts = seed_full(get_settings().database_url)
        print("\nFull demo dataset built (synthetic: not market findings). Rows per view:")
        for view, n in counts.items():
            print(f"  {view:<32} {n:>6}")
        return

    counts = run_ingestion(FixtureClient(), queries=TARGET_QUERIES)
    for query, n in counts.items():
        logging.info("Seeded %r: %d jobs", query, n)
    summarize()
    print("\nDemo data loaded. Open notebooks/01_initial_exploration.ipynb to explore it.")


if __name__ == "__main__":
    main()
