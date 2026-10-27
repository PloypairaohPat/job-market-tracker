"""Render a report from the SQL views.

Run:  python -m src.reports <slug> [--out DIR]     (or: make report REPORT=<slug>)
      python -m src.reports --list

Reads DATABASE_URL (the views must be applied: make views). Writes
<out>/<slug>/report.md and its PNG charts, overwriting the previous render.
Default --out is reports/ in the repo root, which is gitignored: rendered
reports carry real numbers and are never committed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine

from src.reports.catalog import REPORTS, generate
from src.reports.guardrails import GuardrailError
from src.reports.provenance import REPO_ROOT
from src.reports.views import ViewReader
from src.utils.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.reports", description=__doc__.split("\n")[0]
    )
    parser.add_argument("slug", nargs="?", choices=sorted(REPORTS), help="which report")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "reports", help="output directory")
    parser.add_argument("--list", action="store_true", help="list the reports and exit")
    args = parser.parse_args(argv)

    if args.list or not args.slug:
        for slug, module in sorted(REPORTS.items()):
            print(f"{slug:32} {module.TITLE}")
        return 0 if args.list else 2

    engine = create_engine(get_settings().database_url)
    try:
        path = generate(args.slug, ViewReader(engine), args.out)
    except GuardrailError as exc:
        print(f"report not rendered: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    charts = sorted(p.name for p in path.parent.glob("*.png"))
    print(f"wrote {path} ({len(charts)} chart(s): {', '.join(charts)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
