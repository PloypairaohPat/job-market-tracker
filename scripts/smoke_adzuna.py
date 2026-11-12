"""Smoke test for live Adzuna credentials.

Usage:  python scripts/smoke_adzuna.py [--sort-by VALUE]

Makes ONE API call and prints the first 10 job titles. Run this after
putting real credentials in .env (Step 3 of the Phase 1 milestone) to
confirm the account works before running full ingestion.

`--sort-by VALUE` sends VALUE as Adzuna's `sort_by` parameter on that one
call, to check the API accepts it before ADZUNA_SORT_BY is set
(docs/daily-operation.md). Accepted values come from Adzuna's API
documentation; this script doesn't validate them.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python scripts/x.py`

from src.ingestion.adzuna_client import AdzunaClient
from src.utils.config import get_settings

logging.basicConfig(level=logging.INFO)


def main(argv: list[str] | None = None) -> None:
    argp = argparse.ArgumentParser(description="One live Adzuna call.")
    argp.add_argument("--sort-by", default=None, help="send this as Adzuna's sort_by")
    args = argp.parse_args(argv)
    filters = {"sort_by": args.sort_by} if args.sort_by else {}
    settings = get_settings(require_adzuna=True)
    client = AdzunaClient(
        app_id=settings.adzuna_app_id,
        app_key=settings.adzuna_app_key,
        max_calls=1,  # smoke test = exactly one call against the monthly budget
    )
    response = client.search("data analyst", results_per_page=10, **filters)
    if args.sort_by:
        print(
            f"\nThe API answered a search with sort_by={args.sort_by!r} (an HTTP error would "
            "have stopped this script). Check the order of the titles below matches the sort."
        )
    print(f"\nTotal matching postings reported by Adzuna: {response.get('count'):,}")
    print(f"Mean advertised salary: ${response.get('mean', 0):,.0f}\n")
    for i, job in enumerate(response.get("results", []), 1):
        company = (job.get("company") or {}).get("display_name", "(no company)")
        print(f"{i:2d}. {job.get('title')}  —  {company}")


if __name__ == "__main__":
    main()
