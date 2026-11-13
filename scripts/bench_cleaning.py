"""Time the cleaning and skills steps on N synthetic jobs (no real data).

Usage:  python scripts/bench_cleaning.py --n 5000 20000 [--database-url URL] [--json]

For each N it DROPS AND RECREATES the public schema of the target database,
inserts N invented jobs (companies, locations, a USAJobs share with stored
raw pages carrying KeyRequirements), then times each step of
`src.cleaning.apply_cleaning` and the skills step (sync_taxonomy +
extract_for_all_jobs), and counts the SQL statements each step sends (an executemany counts
once per parameter set: psycopg2 sends each one separately).

It refuses any database that isn't on localhost or whose name lacks "test"
or "demo" (the same guard as the demo seed). The default URL is
TEST_DATABASE_URL. Timings depend on the machine: compare runs from one
machine only. Nothing here is a finding.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow `python scripts/x.py`

from sqlalchemy import create_engine, event, text

from src.cleaning import apply_cleaning, extract_skills
from src.dashboard.demo_dataset import assert_demo_database
from src.models import Base
from src.utils.db import dispose_engines, get_engine, session_scope

SEED = 20261113
NOW = datetime(2026, 3, 2, 12, tzinfo=UTC)

TITLES = [
    "Data Analyst",
    "Senior Data Analyst",
    "Jr. Business Intelligence Analyst",
    "Lead Analytics Engineer",
    "Marketing Analyst II",
    "Product Analyst (Remote)",
    "Staff Data Scientist",
    "Management and Program Analyst",
    "IT Specialist (DATAMGT)",
    "Operations Research Analyst",
]
SENTENCES = [
    "You will build dashboards in Tableau and Power BI for the sales team.",
    "Strong SQL and Python required; experience with dbt and Snowflake a plus.",
    "This is a fully remote position open to candidates across the US.",
    "Hybrid schedule: three days a week in our downtown office.",
    "Work with Excel, Looker and Google Analytics to report on campaigns.",
    "Applicants must be U.S. citizens and able to obtain a Secret clearance.",
    "We are unable to sponsor visas now or in the future.",
    "Experience with A/B testing, regression and statistics is expected.",
    "Telework: Ad hoc. Relocation expenses will not be paid.",
    "Familiarity with Airflow, Spark and AWS is helpful.",
    "Our university research center welcomes applicants on OPT.",
    "Bring curiosity and clear communication to a small team.",
]
CITIES = [
    ("New York", "NY"),
    ("San Francisco", "CA"),
    ("Chicago", "IL"),
    ("Austin", "TX"),
    ("Seattle", "WA"),
    ("Washington", "DC"),
    ("Arlington", "VA"),
    ("Boston", "MA"),
    ("Columbus", "OH"),
    ("Denver", "CO"),
]
STEPS = (*apply_cleaning.ALL_STEPS, "skills")


def reset_schema(database_url: str) -> None:
    assert_demo_database(database_url)
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("drop schema public cascade"))
            conn.execute(text("create schema public"))
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def seed(database_url: str, n: int) -> None:
    """N invented jobs; every fifth is USAJobs with a stored raw page."""
    rng = random.Random(SEED + n)
    with session_scope(database_url) as s:
        conn = s.connection()
        n_companies = max(n // 10, 1)
        conn.execute(
            text("insert into companies (canonical_name, raw_names) values (:c, '{}')"),
            [{"c": f"FAKECO Bench {i} Inc."} for i in range(n_companies)],
        )
        conn.execute(
            text(
                "insert into locations (city, state, country, is_remote) "
                "values (:city, :state, 'US', false)"
            ),
            [{"city": c, "state": st} for c, st in CITIES],
        )
        company_ids = conn.execute(text("select id from companies order by id")).scalars().all()
        location_ids = conn.execute(text("select id from locations order by id")).scalars().all()
        raw_ids = []
        for page in range(max(n // 5 // 25, 1) + 1):
            items = [
                {
                    "MatchedObjectId": f"bench-usa-{page * 25 + k}",
                    "MatchedObjectDescriptor": {
                        "UserArea": {
                            "Details": {
                                "KeyRequirements": rng.choice(
                                    [["U.S. Citizenship is required."], [], ["Background check"]]
                                )
                            }
                        }
                    },
                }
                for k in range(25)
            ]
            raw_ids.append(
                conn.execute(
                    text(
                        "insert into raw_responses (source, fetched_at, endpoint, params, "
                        "response) values ('usajobs', :now, 'search', "
                        "cast(:p as jsonb), cast(:r as jsonb)) returning id"
                    ),
                    {
                        "now": NOW,
                        "p": json.dumps({"Keyword": "data analyst", "Page": page + 1}),
                        "r": json.dumps({"SearchResult": {"SearchResultItems": items}}),
                    },
                ).scalar_one()
            )
        rows = []
        usa = 0
        for i in range(n):
            federal = i % 5 == 0
            text_ = " ".join(rng.sample(SENTENCES, rng.randint(2, 6)))
            salary = rng.choice([None, (60000, 90000), (40, 55), (0, 0), (95000, None)])
            row = {
                "e": f"bench-usa-{usa}" if federal else f"bench-adz-{i}",
                "s": "usajobs" if federal else "adzuna",
                "t": rng.choice(TITLES),
                "d": text_[:500],
                "f": text_ + " Duties: analyze data." if federal else None,
                "mn": salary[0] if salary else None,
                "mx": salary[1] if salary else None,
                "p": ("hour" if salary and salary[0] < 1000 else "year") if salary else None,
                "c": rng.choice(company_ids),
                "loc": rng.choice(location_ids),
                "cat": "IT Jobs" if not federal else None,
                "raw": raw_ids[usa // 25] if federal else None,
                "now": NOW,
            }
            usa += int(federal)
            rows.append(row)
        conn.execute(
            text(
                "insert into jobs (external_id, source, title, description, description_full, "
                "salary_min, salary_max, salary_period, company_id, location_id, category, "
                "raw_response_id, is_remote, first_seen_at, last_seen_at) values (:e, :s, :t, "
                ":d, :f, :mn, :mx, :p, :c, :loc, :cat, :raw, false, :now, :now)"
            ),
            rows,
        )


def time_steps(database_url: str, candidates_out: Path) -> dict[str, dict]:
    engine = get_engine(database_url)
    counter = {"n": 0}

    def count(_conn, _cursor, _statement, parameters, _context, executemany) -> None:
        # psycopg2's executemany is one round trip per parameter set; a batched
        # "insertmanyvalues" INSERT arrives as one statement with a dict
        many = executemany and isinstance(parameters, (list, tuple))
        counter["n"] += len(parameters) if many else 1

    event.listen(engine, "before_cursor_execute", count)
    results: dict[str, dict] = {}
    try:
        for step in STEPS:
            counter["n"] = 0
            start = time.perf_counter()
            with session_scope(database_url) as s:
                if step == "skills":
                    ids = extract_skills.sync_taxonomy(s)
                    extract_skills.extract_for_all_jobs(s, ids)
                else:
                    apply_cleaning.run_steps(s, (step,), candidates_out)
            results[step] = {
                "seconds": round(time.perf_counter() - start, 2),
                "statements": counter["n"],
            }
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return results


def main() -> None:
    argp = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argp.add_argument("--n", type=int, nargs="+", default=[5000, 20000])
    argp.add_argument("--database-url", default=os.environ.get("TEST_DATABASE_URL", ""))
    argp.add_argument("--json", action="store_true")
    args = argp.parse_args()
    if not args.database_url:
        argp.error("set TEST_DATABASE_URL or pass --database-url")
    assert_demo_database(args.database_url)

    out: dict[int, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for n in args.n:
            dispose_engines()
            reset_schema(args.database_url)
            seed(args.database_url, n)
            out[n] = time_steps(args.database_url, Path(tmp) / "candidates.csv")
    dispose_engines()
    if args.json:
        print(json.dumps(out, indent=2))
        return
    print(f"{'step':<10}" + "".join(f"{'N=' + str(n):>22}" for n in out))
    for step in STEPS:
        cells = "".join(
            f"{out[n][step]['seconds']:>10.2f}s {out[n][step]['statements']:>8} st" for n in out
        )
        print(f"{step:<10}{cells}")
    total = "".join(f"{sum(r['seconds'] for r in out[n].values()):>10.2f}s {'':>11}" for n in out)
    print(f"{'total':<10}{total}")


if __name__ == "__main__":
    main()
