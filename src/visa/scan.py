"""Print the visa outlook for in-scope jobs, with the evidence.

Run:  python -m src.visa.scan [--bucket strong] [--metro NYC] [--limit 50] [--csv data/visa_scan.csv]

Reads v_job_visa_outlook (apply views with `make views`, and run
`python -m src.cleaning.apply_cleaning --only visa` first). Output is
job-level posting signals plus EMPLOYER-LEVEL LCA aggregates only --
nothing row-level from lca_cases (no case numbers, job titles or wages
of individual filings) is ever printed or written.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.utils.db import session_scope

BUCKETS = ("strong", "possible", "unknown", "closed")

# Columns exposed by the scan: job fields + posting signals + employer-level
# aggregates from v_employer_sponsorship. Explicit, so a future view column
# never leaks into output by accident.
OUTPUT_COLUMNS = [
    "job_id",
    "source",
    "title",
    "company",
    "metro_area",
    "bucket",
    "bucket_reason",
    "restriction",
    "restriction_reason",
    "sponsorship_stance",
    "sponsorship_reason",
    "opt_mentioned",
    "text_coverage",
    "cap_exempt_hint",
    "cap_exempt_reason",
    "employer_matched",
    "lca_window_start_fy",
    "lca_window_end_fy",
    "certified_h1b_lcas",
    "certified_h1b_new_employment",
    "certified_h1b_analytics_soc",
    "certified_h1b_analytics_soc_new_employment",
    "wage_level_i",
    "wage_level_ii",
    "wage_level_iii",
    "wage_level_iv",
    "wage_level_na_or_missing",
    "median_offered_annual_wage",
    "any_h1b_dependent",
    "any_willful_violator",
    "redirect_url",
]


def fetch_outlook(
    session: Session,
    bucket: str | None = None,
    metro: str | None = None,
    limit: int | None = 50,
) -> list[dict]:
    sql = f"""
        select {", ".join(OUTPUT_COLUMNS)}
        from v_job_visa_outlook
        where (cast(:bucket as text) is null or bucket = :bucket)
          and (cast(:metro as text) is null or lower(metro_area) = lower(:metro))
        order by array_position(array['strong','possible','unknown','closed'], bucket),
                 certified_h1b_analytics_soc_new_employment desc,
                 certified_h1b_lcas desc,
                 job_id
        limit :limit
    """
    rows = session.execute(text(sql), {"bucket": bucket, "metro": metro, "limit": limit})
    return [dict(r) for r in rows.mappings()]


def format_job(row: dict) -> str:
    lines = [
        f"[{row['bucket'].upper()}] {row['title']} -- {row['company'] or '(no company)'}"
        f" -- {row['metro_area'] or '(no tracked metro)'}",
        f"  why: {row['bucket_reason']}",
        f"  posting ({row['text_coverage'] or 'unclassified'} text):"
        f" restriction={row['restriction']}"
        + (f" [{row['restriction_reason']}]" if row["restriction_reason"] else "")
        + f"; stance={row['sponsorship_stance']}"
        + (f" [{row['sponsorship_reason']}]" if row["sponsorship_reason"] else "")
        + f"; OPT mentioned={'yes' if row['opt_mentioned'] else 'no'}",
        f"  cap-exempt hint: {row['cap_exempt_hint']}"
        + (f" [{row['cap_exempt_reason']}]" if row["cap_exempt_reason"] else ""),
    ]
    if row["employer_matched"]:
        lca = (
            f"  LCAs FY{row['lca_window_start_fy']}-FY{row['lca_window_end_fy']}:"
            f" {row['certified_h1b_lcas']} certified H-1B"
            f" ({row['certified_h1b_new_employment']} new employment,"
            f" {row['certified_h1b_analytics_soc']} analytics SOC,"
            f" {row['certified_h1b_analytics_soc_new_employment']} both);"
            f" wage levels I/II/III/IV/NA = {row['wage_level_i']}/{row['wage_level_ii']}/"
            f"{row['wage_level_iii']}/{row['wage_level_iv']}/{row['wage_level_na_or_missing']}"
        )
        if row["median_offered_annual_wage"] is not None:
            lca += f"; median offered ${row['median_offered_annual_wage']:,.0f}"
        lines.append(lca)
        flags = [
            name
            for name, on in (
                ("H-1B dependent", row["any_h1b_dependent"]),
                ("willful violator", row["any_willful_violator"]),
            )
            if on
        ]
        if flags:
            lines.append(f"  employer flags: {', '.join(flags)}")
    else:
        lines.append("  LCAs: no employer match")
    lines.append(f"  {row['redirect_url'] or '(no url)'}")
    return "\n".join(lines)


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    argp = argparse.ArgumentParser(description="Visa outlook for in-scope jobs.")
    argp.add_argument("--bucket", choices=BUCKETS)
    argp.add_argument("--metro", help="metro_area, e.g. NYC, 'SF Bay Area', DC")
    argp.add_argument("--limit", type=int, default=50)
    argp.add_argument("--csv", type=Path, help="also write the rows to this CSV (keep under data/)")
    args = argp.parse_args()

    with session_scope() as session:
        rows = fetch_outlook(session, args.bucket, args.metro, args.limit)
    for row in rows:
        print(format_job(row))
        print()
    counts = {b: sum(r["bucket"] == b for r in rows) for b in BUCKETS}
    print(f"{len(rows)} jobs shown: " + ", ".join(f"{b}={n}" for b, n in counts.items()))
    if args.csv:
        write_csv(rows, args.csv)
        print(f"wrote {args.csv}")


if __name__ == "__main__":
    main()
