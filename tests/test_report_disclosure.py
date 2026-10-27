"""Report 2, how much employers disclose (src/reports/disclosure.py), and its
counts view v_field_completeness_counts.

Regenerate the golden file after an intended change with UPDATE_GOLDEN=1 and
review the diff.
"""

import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from scripts.seed_demo_data import seed_full
from src.reports import disclosure
from src.reports.__main__ import main
from src.reports.guardrails import GuardrailError, round_half_up
from src.reports.provenance import DEMO_BANNER, Provenance
from src.reports.views import VIEWS_DIR
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
GOLDEN = Path(__file__).parent / "fixtures" / "reports" / f"{disclosure.SLUG}.md"
KEYS = [f.key for f in disclosure.FIELDS]

# --------------------------------------------------------------------- #
# hand-built view frames (invented numbers)

COUNTS = {  # field key -> (commercial, federal)
    "jobs": (800, 50),
    "salary_present": (800, 50),
    "salary_disclosed": (96, 50),
    "salary_predicted": (704, 0),
    "skill_present": (340, 49),
    "location_present": (800, 38),
    "company_present": (799, 50),
    "posted_at_present": (800, 50),
    "seniority_present": (400, 4),
    "metro_present": (72, 11),
    "remote_true": (32, 0),
}


def frames(**overrides) -> dict[str, pd.DataFrame]:
    markets = ("commercial", "federal")
    counts, pcts = [], []
    for i, market in enumerate(markets):
        n_jobs = COUNTS["jobs"][i]
        counts.append(
            {"market": market, "n_jobs": n_jobs, **{f"n_{k}": COUNTS[k][i] for k in KEYS}}
        )
        pcts.append(
            {
                "market": market,
                "n_jobs": n_jobs,
                **{
                    f"pct_{k}": round_half_up(100 * COUNTS[k][i] / n_jobs)
                    for k in KEYS
                    if k != "salary_predicted"  # v_field_completeness has no such column
                },
            }
        )
    out = {
        "v_field_completeness": pd.DataFrame(pcts),
        "v_field_completeness_counts": pd.DataFrame(counts),
    }
    out.update(overrides)
    return out


def stamp():
    return Provenance(
        database="jobmarket_test_golden",
        generated_at=datetime(2026, 10, 27, 3, 0, tzinfo=UTC),
        git_commit="golden000000",
        view_rows={v: 2 for v in disclosure.VIEWS},
    )


def test_the_report_matches_its_golden_file(tmp_path):
    path = disclosure.render(disclosure.compute(frames()), stamp(), tmp_path)
    rendered = path.read_text()
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(rendered)
    assert rendered == GOLDEN.read_text()
    assert (path.parent / "measured-fields.png").stat().st_size > 10_000


def test_measured_and_instrument_limited_fields_stay_apart(tmp_path):
    md = disclosure.render(disclosure.compute(frames()), stamp(), tmp_path).read_text()
    measured, limited = md.split("## 3. Instrument-limited fields")[0], md.split("## 3.")[1]
    assert (
        "| Salary | employer-disclosed | 12.0% (96 of 800 jobs) | 100.0% (50 of 50 jobs) |"
        in measured
    )
    assert (
        "| Salary | Adzuna model estimate | 88.0% (704 of 800 jobs) | 0.0% (0 of 50 jobs) |"
        in measured
    )
    for name in ("Seniority", "Metro", "Remote"):
        assert f"| {name} |" not in measured and f"| {name} |" in limited
    # federal remote is not measurable: never a rate, not even 0 of 50
    assert "| Remote | flagged remote | 4.0% (32 of 800 jobs) | not measurable |" in limited
    assert "Federal Remote: flagged remote: not measurable" in md
    assert "(0 of 50 jobs) | the classifier scans" not in md
    for section in ("Headline", "What it means", "What to do about it"):
        assert f"**[TO WRITE: {section}]**" in md
    assert md.index(DEMO_BANNER) < md.index("# How much employers disclose")


def test_instrument_limited_fields_can_never_be_charted():
    disclosure.check_charted(disclosure.CHARTED)
    assert all(disclosure.BY_KEY[k].measured for k in disclosure.CHARTED)
    with pytest.raises(GuardrailError, match="instrument-limited"):
        disclosure.check_charted(["salary_disclosed", "metro_present"])


def test_counts_that_dont_reproduce_the_percentage_view_stop_the_report():
    counts = frames()["v_field_completeness_counts"].copy()
    counts.loc[counts["market"] == "commercial", "n_salary_disclosed"] = 180  # view says 12.0%
    with pytest.raises(GuardrailError, match="wrong denominator"):
        disclosure.compute(frames(v_field_completeness_counts=counts))
    counts = frames()["v_field_completeness_counts"].copy()
    counts.loc[counts["market"] == "federal", "n_jobs"] = 70
    with pytest.raises(GuardrailError):
        disclosure.compute(frames(v_field_completeness_counts=counts))
    only_commercial = frames()["v_field_completeness_counts"].iloc[:1]
    with pytest.raises(GuardrailError, match="disagree on markets"):
        disclosure.compute(frames(v_field_completeness_counts=only_commercial))


def test_every_field_has_its_count_and_percentage_columns():
    def body(view):
        return re.sub(r"--[^\n]*", "", (VIEWS_DIR / f"{view}.sql").read_text())

    for key in KEYS:
        assert f"AS n_{key}" in body("v_field_completeness_counts")
        if key != "salary_predicted":
            assert f"AS pct_{key}" in body("v_field_completeness")


# --------------------------------------------------------------------- #
# the counts view and the report on the full demo seed


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    if not TEST_DB_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path_factory.mktemp("d") / "c.csv")
    yield engine
    engine.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


@pytest.mark.integration
def test_the_counts_view_reproduces_every_completeness_percentage(demo):
    with demo.connect() as conn:
        pct = {r.market: r for r in conn.execute(text("select * from v_field_completeness"))}
        counts = {
            r.market: r for r in conn.execute(text("select * from v_field_completeness_counts"))
        }
    assert set(pct) == set(counts) == {"commercial", "federal"}
    for market, c in counts.items():
        assert c.n_jobs == pct[market].n_jobs
        for key in KEYS:
            if key == "salary_predicted":
                continue
            expected = round_half_up(100 * getattr(c, f"n_{key}") / c.n_jobs)
            assert float(getattr(pct[market], f"pct_{key}")) == expected, (market, key)
        assert c.n_salary_disclosed + c.n_salary_predicted <= c.n_salary_present


@pytest.mark.integration
def test_end_to_end_on_the_demo_seed(demo, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    assert main([disclosure.SLUG, "--out", str(tmp_path)]) == 0
    md = (tmp_path / disclosure.SLUG / "report.md").read_text()
    assert f"> **{DEMO_BANNER}**" in md and "| Database | `jobmarket_test` |" in md
    assert "| Rows in `v_field_completeness_counts` | 2 |" in md
    assert (tmp_path / disclosure.SLUG / "measured-fields.png").exists()
    assert not re.search(r"\bnan\b|\bNone\b", md, re.IGNORECASE)
