"""Render a report from the SQL views.

Run:  python -m src.reports <slug> [--out DIR]     (or: make report REPORT=<slug>)
      python -m src.reports --list
      python -m src.reports <slug> --init-narrative
      python -m src.reports <slug> --publish
      python -m src.reports --index

Reads DATABASE_URL (the views must be applied: make views). A plain render
writes <out>/<slug>/report.md and its PNG charts, overwriting the previous
render. Default --out is reports/ in the repo root, which is gitignored:
renders, and anything from a demo or test database, are never committed.

--init-narrative creates docs/reports/<slug>/narrative.md (never overwrites).
--publish renders with that narrative merged in and writes the tracked
docs/reports/<slug>/report.md and its PNGs, then refreshes the README's
published-reports block. It refuses a demo or test database. --index only
refreshes the README block. See docs/reports.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine

from src.reports import publish as pub
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--init-narrative",
        action="store_true",
        help="create docs/reports/<slug>/narrative.md with one heading per section",
    )
    mode.add_argument(
        "--publish",
        action="store_true",
        help="render with the narrative merged in, into docs/reports/<slug>/ (tracked)",
    )
    mode.add_argument(
        "--index", action="store_true", help="refresh the README's published-reports block"
    )
    args = parser.parse_args(argv)

    if args.index:
        changed = pub.update_index()
        print(f"README published-reports block {'updated' if changed else 'already current'}")
        return 0

    if args.list or not args.slug:
        for slug, module in sorted(REPORTS.items()):
            print(f"{slug:32} {module.TITLE}")
        return 0 if args.list else 2

    if args.init_narrative:
        path, created = pub.init_narrative(args.slug)
        if created:
            print(f"created {path}: write each section, then run --publish")
        else:
            print(f"{path} already exists: left unchanged")
        return 0

    engine = create_engine(get_settings().database_url)
    try:
        if args.publish:
            return _publish(args.slug, ViewReader(engine))
        path = generate(args.slug, ViewReader(engine), args.out)
    except GuardrailError as exc:
        print(f"report not rendered: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:  # e.g. --out not writable by this user
        print(f"report not written to {args.out}: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    charts = sorted(p.name for p in path.parent.glob("*.png"))
    print(f"wrote {path} ({len(charts)} chart(s): {', '.join(charts)})")
    return 0


def _publish(slug: str, reader: ViewReader) -> int:
    for changed in pub.uncommitted_report_inputs():
        print(
            f"warning: {changed} has uncommitted changes; the provenance commit won't "
            "describe the code that rendered this report",
            file=sys.stderr,
        )
    try:
        result = pub.publish(slug, reader)
    except pub.PublishRefused as exc:
        print(f"report not published: {exc}", file=sys.stderr)
        return 1
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(
        f"published {result.path} ({len(result.charts)} chart(s)); README block refreshed. "
        f"Review, then commit docs/reports/{slug}/ and README.md."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
