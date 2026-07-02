"""Seed the database with synthetic demo data — no API key required.

Usage:  python scripts/seed_demo_data.py

Loads the synthetic fixture pages from tests/fixtures/ through the real
ingestion pipeline, so anyone cloning the repo can exercise the full
stack (schema, upserts, notebook) before registering for Adzuna
credentials. Demo rows are ordinary rows; wipe with `alembic downgrade
base && alembic upgrade head` before real ingestion if you want a clean
dataset.
"""

import copy
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python scripts/x.py`

from src.ingestion.adzuna_client import AdzunaClient
from src.ingestion.ingest_adzuna import TARGET_QUERIES, run_ingestion, summarize

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


class FixtureClient(AdzunaClient):
    """Serves local fixture pages instead of calling the network."""

    def __init__(self):
        super().__init__(app_id="demo", app_key="demo", min_request_interval=0.0)
        self._pages = [
            json.loads((FIXTURES / "adzuna_page_1.json").read_text()),
            json.loads((FIXTURES / "adzuna_page_2.json").read_text()),
        ]

    def iter_search(self, query, max_results=1000, results_per_page=50, **filters):
        # Give each query a distinct slice of IDs so the demo DB has volume.
        offset = abs(hash(query)) % 900_000
        for i, page in enumerate(self._pages, start=1):
            page = copy.deepcopy(page)
            for job in page["results"]:
                job["id"] = str(int(job["id"]) + offset)
            yield i, page


def main() -> None:
    counts = run_ingestion(FixtureClient(), queries=TARGET_QUERIES)
    for query, n in counts.items():
        logging.info("Seeded %r: %d jobs", query, n)
    summarize()
    print("\nDemo data loaded. Open notebooks/01_initial_exploration.ipynb to explore it.")


if __name__ == "__main__":
    main()
