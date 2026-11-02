"""Report 4, what commercial data-analyst postings pay (src/reports/salary.py).

The golden file is rendered from hand-built view frames with invented
salaries and FAKE titles. Regenerate it after an intended change with
UPDATE_GOLDEN=1 and review the diff.
"""

import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from scripts.seed_demo_data import seed_full
from src.reports import salary
from src.reports.__main__ import main
from src.reports.catalog import REPORTS
from src.reports.guardrails import MEDIAN_RATIONALE, SALARY_FLOOR
from src.reports.provenance import DEMO_BANNER, Provenance
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
GOLDEN = Path(__file__).parent / "fixtures" / "reports" / f"{salary.SLUG}.md"

# --------------------------------------------------------------------- #
# hand-built view frames (invented numbers, FAKE titles)

# (seniority, metro, n): 40 employer-disclosed postings. senior sits exactly
# at the floor, NULL seniority and NULL metro clear it, mid and junior don't
DISCLOSED = [
    ("senior", "Chicago", 10),
    ("senior", None, 5),
    (None, "Chicago", 7),
    (None, None, 9),
    ("mid", "Austin", 6),
    ("junior", "Austin", 2),
    ("junior", None, 1),
]
PREDICTED = 25


def clean_frame(disclosed=DISCLOSED, predicted=PREDICTED):
    rows, job_id = [], 990_001
    base = {"senior": 103_000, "mid": 88_000, "junior": 70_000, None: 92_000}
    for seniority, metro, n in disclosed:
        for i in range(n):
            mid = base[seniority] + 1_500 * i
            rows.append((job_id, f"FAKE Data Analyst {job_id}", mid, False, seniority, metro))
            job_id += 1
    for i in range(predicted):  # predicted runs higher: pooling would move the median
        mid = 121_000 + 2_000 * i
        rows.append((job_id, f"FAKE Data Analyst {job_id}", mid, True, "senior", "NYC"))
        job_id += 1
    frame = pd.DataFrame(
        rows,
        columns=[
            "job_id",
            "title",
            "salary_midpoint",
            "salary_is_predicted",
            "seniority",
            "metro_area",
        ],
    )
    frame["salary_min"] = frame["salary_midpoint"] - 5_000
    frame["salary_max"] = frame["salary_midpoint"] + 5_000
    return frame


def population_frame():
    rows = [
        (None, None, None, False, 30, False),
        ("ok", "USD", "year", False, 40, True),
        ("ok", "USD", "year", True, 25, True),
        ("suspect_outlier_high", "USD", "year", True, 3, False),
        ("ok", "GBP", "year", False, 2, False),
    ]
    frame = pd.DataFrame(
        rows,
        columns=[
            "salary_quality",
            "salary_currency",
            "salary_period",
            "salary_is_predicted",
            "n",
            "in_clean_population",
        ],
    )
    return frame.assign(market_n_postings=int(frame["n"].sum()))


def coverage_frame(disclosed_at_floor=0):
    return pd.DataFrame(
        [("employer-disclosed", 40, 9, 4, disclosed_at_floor), ("Adzuna-predicted", 25, 12, 7, 0)],
        columns=["basis", "n_jobs", "n_jobs_tagged", "largest_skill_n", "n_skills_at_floor"],
    )


def daily_frame():
    start = date(2026, 10, 20)
    rows = [(start + timedelta(days=k), "adzuna") for k in range(5)]
    rows += [(start + timedelta(days=k), "usajobs") for k in range(7)]
    return pd.DataFrame(rows, columns=["snapshot_date", "source"])


def frames(**overrides):
    out = {
        "v_commercial_salary_clean": clean_frame(),
        "v_salary_population": population_frame(),
        "v_salary_skill_coverage": coverage_frame(),
        "v_ingestion_daily": daily_frame(),
    }
    out.update(overrides)
    return out


def stamp():
    return Provenance(
        database="jobmarket_test_golden",
        generated_at=datetime(2026, 10, 27, 3, 0, tzinfo=UTC),
        git_commit="golden000000",
        view_rows={v: 2 for v in salary.VIEWS},
    )


def render(tmp_path, **kwargs):
    return salary.render(salary.compute(frames(**kwargs)), stamp(), tmp_path).read_text()


def section(md: str, start: str, end: str) -> str:
    return md[md.index(start) : md.index(end)]


# --------------------------------------------------------------------- #


def test_the_report_matches_its_golden_file(tmp_path):
    rendered = render(tmp_path)
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(rendered)
    assert rendered == GOLDEN.read_text()
    for chart in ("disclosed-vs-predicted.png", "disclosed-by-seniority.png"):
        assert (tmp_path / salary.SLUG / chart).stat().st_size > 10_000


def test_it_is_in_the_catalog():
    assert REPORTS[salary.SLUG] is salary and len(REPORTS) == 4


def test_disclosed_and_predicted_are_never_pooled(tmp_path):
    data = salary.compute(frames())
    clean = clean_frame()
    disclosed = clean.loc[~clean["salary_is_predicted"], "salary_midpoint"].median()
    pooled = clean["salary_midpoint"].median()
    assert data.disclosed.median == disclosed != pooled  # pooling would move it
    assert data.disclosed.n == 40 and data.predicted.n == 25
    md = render(tmp_path)
    anchor = section(md, "## 2. The disclosed anchor", "## 3. Predicted")
    assert f"${disclosed:,.0f} (IQR" in anchor and f"${pooled:,.0f} (IQR" not in anchor
    assert "+$" in data.diff.render() and "n=25 vs employer-disclosed" in data.diff.render()


def test_the_headline_quotes_only_the_disclosed_median(tmp_path):
    headline = section(render(tmp_path), "## Headline", "## 1. Who is measured")
    figures = re.findall(r"\$[\d,]+ \(IQR", headline)
    assert len(figures) == 1 and "employer-disclosed)" in headline
    assert "Adzuna-predicted" not in headline


def test_groups_under_the_floor_show_n_but_no_median(tmp_path):
    md = render(tmp_path)
    seniority = section(md, "## 4. Disclosed by seniority", "## 5. Disclosed by metro")
    assert "| mid | 15.0% (6 of 40 postings) | withheld: n=6 is under the n ≥ 15 floor" in seniority
    assert "| senior | 37.5% (15 of 40 postings) | $" in seniority  # exactly at the floor
    assert "| no title signal | 40.0% (16 of 40 postings) | $" in seniority  # NULL: its own row
    assert "| lead" not in seniority  # no lead postings: no empty row
    metro = section(md, "## 5. Disclosed by metro", "## 6. Why")
    assert "| Austin | 20.0% (8 of 40 postings) | withheld: n=8" in metro
    assert "| not on the tracked metro list | 37.5% (15 of 40 postings) | $" in metro
    # the seniority chart draws only the groups that clear the floor
    data = salary.compute(frames())
    assert [g.group for g in salary._cleared(data.by_seniority)] == ["senior", "no title signal"]


def test_without_enough_disclosed_postings_nothing_is_compared(tmp_path):
    few = clean_frame(disclosed=[("senior", "Chicago", SALARY_FLOOR - 1)])
    md = render(tmp_path, v_commercial_salary_clean=few)
    comparison = section(md, "## 3. Predicted vs disclosed", "## 4. Disclosed by seniority")
    assert "not shown: employer-disclosed under the n ≥ 15 floor" in comparison
    assert "No chart: both bases need n ≥ 15" in comparison
    assert not (tmp_path / salary.SLUG / "disclosed-vs-predicted.png").exists()
    assert "withheld: n=14" in section(md, "## Headline", "## 1. Who")


def test_no_mean_no_titles_no_job_ids(tmp_path):
    md = render(tmp_path)
    assert md.count(MEDIAN_RATIONALE) == 1
    without = md.replace(MEDIAN_RATIONALE, "")
    assert not re.search(r"\b(mean|average|avg)\b", without, re.IGNORECASE)
    clean = clean_frame()
    assert "FAKE Data Analyst" not in md
    assert not any(str(j) in md for j in clean["job_id"])


def test_the_disclosed_basis_reaching_the_floor_is_said_and_still_no_premium(tmp_path):
    md = render(tmp_path, v_salary_skill_coverage=coverage_frame(disclosed_at_floor=2))
    skills = section(md, "## 6. Why there are no skill premiums here", "## 7. Over time")
    assert "on this data 2 skill(s) reach n ≥ 15 among employer-disclosed postings" in skills
    assert "no premium is computed" in skills
    assert "Too few disclosed postings carry tags" not in skills
    below = section(render(tmp_path), "## 6. Why", "## 7. Over time")
    assert "Too few disclosed postings carry tags" in below
    assert "| employer-disclosed | 40 | 22.5% (9 of 40 jobs) | 4 | 0 |" in below


def test_over_time_counts_commercial_snapshot_days_only(tmp_path):
    md = render(tmp_path)
    assert "- Distinct commercial snapshot days so far (2026-10-20 to 2026-10-24): 5" in md
    assert "computes no trend" in md


def test_empty_frames_render_no_data(tmp_path):
    empty = {
        view: frame.iloc[0:0]
        for view, frame in frames().items()
        if view != "v_salary_skill_coverage"
    }
    zero = coverage_frame().assign(n_jobs=0, n_jobs_tagged=0, largest_skill_n=0)
    md = render(tmp_path, **empty, v_salary_skill_coverage=zero)
    assert "**no data:** no commercial postings in this database." in md
    assert "no data (n=0, employer-disclosed)" in md
    assert not re.search(r"\bnan\b", md, re.IGNORECASE) and not re.search(r"\bNone\b", md)
    assert not list((tmp_path / salary.SLUG).glob("*.png"))


# --------------------------------------------------------------------- #
# end to end on the full demo seed


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_end_to_end_on_the_demo_seed(tmp_path, monkeypatch):
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path / "c.csv")
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    try:
        assert main([salary.SLUG, "--out", str(tmp_path)]) == 0
        md = (tmp_path / salary.SLUG / "report.md").read_text()
        assert f"> **{DEMO_BANNER}**" in md
        with engine.connect() as conn:
            for view in salary.VIEWS:
                n = conn.execute(text(f"select count(*) from {view}")).scalar_one()
                assert f"| Rows in `{view}` | {n:,} |" in md
            disclosed = conn.execute(
                text("select count(*) from v_commercial_salary_clean where not salary_is_predicted")
            ).scalar_one()
        anchor = section(md, "## 2. The disclosed anchor", "## 3. Predicted")
        assert f"n={disclosed:,}, employer-disclosed)" in anchor
        for chart in ("disclosed-vs-predicted.png", "disclosed-by-seniority.png"):
            assert (tmp_path / salary.SLUG / chart).stat().st_size > 10_000
        assert not re.search(r"\bnan\b", md, re.IGNORECASE) and not re.search(r"\bNone\b", md)
        assert "redirect" not in md.lower() and "http" not in md
    finally:
        engine.dispose()
        import src.utils.db as dbmod

        dbmod._engine = None
        dbmod._SessionFactory = None
