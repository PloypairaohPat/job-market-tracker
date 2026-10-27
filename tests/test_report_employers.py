"""Report 3, employers and sponsorship (src/reports/employers.py).

The golden file is rendered from hand-built view frames with invented numbers
and FAKE employer names. Regenerate it after an intended change with
UPDATE_GOLDEN=1 and review the diff.
"""

import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from scripts.seed_demo_data import seed_full
from src.reports import employers
from src.reports.__main__ import main
from src.reports.guardrails import GuardrailError
from src.reports.lca_guardrails import LCA_CAVEATS, REQUIRED_CAVEATS
from src.reports.provenance import DEMO_BANNER, Provenance
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
GOLDEN = Path(__file__).parent / "fixtures" / "reports" / f"{employers.SLUG}.md"
NAN = math.nan

# --------------------------------------------------------------------- #
# hand-built view frames (invented numbers, FAKE names)

COMMERCIAL = [  # 12 employers; the 10th and 11th tie at 3 postings
    ("fake alpha", "FAKE Alpha", 40),
    ("fake bravo", "FAKE Bravo", 25),
    ("fake charlie", "FAKE Charlie", 20),
    ("fake delta", "FAKE Delta", 12),
    ("fake echo", "FAKE Echo", 10),
    ("fake foxtrot", "FAKE Foxtrot", 8),
    ("fake golf", "FAKE Golf", 6),
    ("fake hotel", "FAKE Hotel", 5),
    ("fake india", "FAKE India", 4),
    ("fake juliet", "FAKE Juliet", 3),
    ("fake kilo", "FAKE Kilo", 3),
    ("fake lima", "FAKE Lima", 2),
]
FEDERAL = [("fake agency a", "FAKE Agency A", 6), ("fake agency b", "FAKE Agency B", 4)]
NO_COMPANY = 12  # commercial postings with no company


def postings_frame():
    total_c = sum(n for *_, n in COMMERCIAL) + NO_COMPANY
    total_f = sum(n for *_, n in FEDERAL)
    rows = [("commercial", k, name, n, total_c, len(COMMERCIAL)) for k, name, n in COMMERCIAL]
    rows.append(("commercial", None, None, NO_COMPANY, total_c, len(COMMERCIAL)))
    rows += [("federal", k, name, n, total_f, len(FEDERAL)) for k, name, n in FEDERAL]
    return pd.DataFrame(
        rows,
        columns=[
            "market",
            "employer_key",
            "employer_name",
            "n_postings",
            "market_n_postings",
            "market_n_employers",
        ],
    )


def match_frame(lca_rows=1000, window=(2024, 2026)):
    start, end = window if lca_rows else (NAN, NAN)
    c = (150, 12, 60, 50, 30, 12, 5, 4, 3) if lca_rows else (150, 12, 0, 0, 0, 12, 0, 0, 0)
    f = (10, 0, 0, 0, 0, 2, 0, 0, 0)
    cols = [
        "n_postings",
        "n_postings_no_employer",
        "n_postings_matched",
        "n_postings_certified_h1b",
        "n_postings_analytics_soc",
        "n_employers",
        "n_employers_matched",
        "n_employers_certified_h1b",
        "n_employers_analytics_soc",
    ]
    return pd.DataFrame(
        [
            ("commercial", *c, lca_rows, start, end),
            ("federal", *f, lca_rows, start, end),
        ],
        columns=["market", *cols, "lca_rows_loaded", "lca_window_start_fy", "lca_window_end_fy"],
    )


def outlook_frame():
    rows = [
        ("commercial", "closed", "posting restriction: citizenship", 3),
        ("commercial", "closed", "posting restriction: clearance", 2),
        ("commercial", "closed", "posting: will not sponsor", 5),
        ("commercial", "strong", "posting: will sponsor", 4),
        (
            "commercial",
            "strong",
            "employer: >=3 analytics-SOC new-employment H-1B LCAs in last 3 FYs",
            20,
        ),
        ("commercial", "possible", "employer: certified H-1B LCA(s) in last 3 FYs", 26),
        ("commercial", "unknown", "no signal; no LCA employer match", 85),
        (
            "commercial",
            "unknown",
            "no signal; employer matched but no certified H-1B LCAs in last 3 FYs",
            5,
        ),
        ("federal", "closed", "posting restriction: citizenship", 9),
        ("federal", "unknown", "no signal; no LCA employer match", 1),
    ]
    totals = {"commercial": 150, "federal": 10}
    return pd.DataFrame(
        [(*r, totals[r[0]]) for r in rows],
        columns=["market", "bucket", "bucket_reason", "n_postings", "market_n_postings"],
    )


def wages_frame(loaded=True):
    c = (
        (40, 38, 9, 8, 82_000.0, 95_000.0, 118_000.0, 20)
        if loaded
        else (0, 0, 0, 0, NAN, NAN, NAN, 0)
    )
    return pd.DataFrame(
        [("commercial", *c), ("federal", 0, 0, 0, 0, NAN, NAN, NAN, 0)],
        columns=[
            "market",
            "n_filings",
            "n_filings_with_wage",
            "n_employers",
            "n_employers_with_wage",
            "p25_offered_annual_wage",
            "median_offered_annual_wage",
            "p75_offered_annual_wage",
            "largest_employer_n_filings",
        ],
    )


def frames(loaded=True, **overrides):
    out = {
        "v_employer_postings": postings_frame(),
        "v_employer_sponsorship_match": match_frame(1000 if loaded else 0),
        "v_visa_outlook_summary": outlook_frame(),
        "v_matched_employer_lca_wages": wages_frame(loaded),
    }
    out.update(overrides)
    return out


def stamp():
    return Provenance(
        database="jobmarket_test_golden",
        generated_at=datetime(2026, 10, 27, 3, 0, tzinfo=UTC),
        git_commit="golden000000",
        view_rows={v: 2 for v in employers.VIEWS},
    )


def render(tmp_path, **kwargs):
    return employers.render(employers.compute(frames(**kwargs)), stamp(), tmp_path).read_text()


def sponsorship_sections(md: str) -> str:
    return md[md.index("## 3. Employers with LCA filing history") : md.index("## What it means")]


# --------------------------------------------------------------------- #


def test_the_report_matches_its_golden_file(tmp_path):
    rendered = render(tmp_path)
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(rendered)
    assert rendered == GOLDEN.read_text()
    for market in ("commercial", "federal"):
        assert (tmp_path / employers.SLUG / f"top-employers-{market}.png").stat().st_size > 10_000


def test_hiring_concentration_has_its_denominator_and_tie_note(tmp_path):
    md = render(tmp_path)
    assert md.index(DEMO_BANNER) < md.index(f"# {employers.TITLE}")
    # top 10 of 150 commercial postings (12 have no company: they stay in the denominator)
    assert (
        "- Share of commercial postings from the top 10 employers: 88.7% (133 of 150 postings)"
        in md
    )
    assert "| commercial | 150 | 12 | 8.0% (12 of 150 postings) |" in md
    assert "Several employers tie at place 10" in md
    assert "| #10 | FAKE Juliet | 2.0% (3 of 150 postings) |" in md
    assert "FAKE Kilo" not in md  # 11th: not in the top 10
    assert "- Share of federal postings from the top 2 employers: 100.0% (10 of 10 postings)" in md


def test_sponsorship_numbers_are_aggregate_and_worded_as_filings(tmp_path):
    md = render(tmp_path)
    sponsorship = sponsorship_sections(md)
    for _, name, _ in COMMERCIAL + FEDERAL:  # no employer is named next to sponsorship numbers
        assert name not in sponsorship
    assert (
        "| no match found | 60.0% (90 of 150 postings) | 58.3% (7 of 12 employers) |" in sponsorship
    )
    assert (
        "| ≥ 1 certified H-1B LCA filing | 33.3% (50 of 150 postings) | 33.3% (4 of 12 employers) |"
        in sponsorship
    )
    assert (
        "- Commercial closed postings due to a citizenship or clearance requirement: 50.0% (5 of 10 closed postings)"
        in sponsorship
    )
    assert (
        '| unknown (no signal; never a "no") | 60.0% (90 of 150 postings) | 10.0% (1 of 10 postings) |'
        in sponsorship
    )
    # the wage is on filings, with its n and the largest filer's share
    assert (
        "| commercial | 40 certified analytics-SOC H-1B LCA filings | $95,000 (IQR $82,000–$118,000; "
        "n=38 LCA filings from 8 employer(s)) | 50.0% (20 of 40 filings) | "
        "2 filing(s) without an annual wage |"
    ) in sponsorship
    assert "hires" not in sponsorship.replace("not approvals or hires", "")


def test_methods_carries_every_lca_caveat(tmp_path):
    md = render(tmp_path)
    methods = md[md.index("## Methods and caveats") :]
    for key in REQUIRED_CAVEATS:
        assert LCA_CAVEATS[key] in methods


def test_without_lca_data_the_hiring_sections_still_render(tmp_path):
    md = render(tmp_path, loaded=False)
    assert md.count("**LCA data not loaded.**") == 3  # match, buckets, wages
    assert "src/visa/README.md" in sponsorship_sections(md)
    assert "| #1 | FAKE Alpha | 26.7% (40 of 150 postings) |" in md
    assert "$95,000" not in md and "| no match found |" not in md
    assert "- Commercial employers with ≥ 1 certified H-1B LCA filing: LCA data not loaded" in md
    for key in REQUIRED_CAVEATS:  # the caveats are printed either way
        assert LCA_CAVEATS[key] in md


def test_a_small_filing_pool_is_marked_directional(tmp_path):
    small = wages_frame().assign(
        n_filings=[10, 0], n_filings_with_wage=[10, 0], largest_employer_n_filings=[6, 0]
    )
    md = render(tmp_path, v_matched_employer_lca_wages=small)
    assert "directional: under 15 filings or 5 employers" in md


def test_row_level_frames_and_unsupported_wording_are_refused(tmp_path):
    with_titles = postings_frame().assign(title="Data Analyst")
    with pytest.raises(GuardrailError, match="aggregate and employer-level only"):
        employers.compute(frames(v_employer_postings=with_titles))
    bad = outlook_frame()
    bad.loc[0, "bucket_reason"] = "employer doesn't sponsor"
    with pytest.raises(GuardrailError, match="can't support"):
        render(tmp_path, v_visa_outlook_summary=bad)


# --------------------------------------------------------------------- #
# end to end on the full demo seed, with and without LCA data


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_end_to_end_on_the_demo_seed(tmp_path, monkeypatch):
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path / "c.csv")
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    try:
        assert main([employers.SLUG, "--out", str(tmp_path / "with")]) == 0
        md = (tmp_path / "with" / employers.SLUG / "report.md").read_text()
        assert f"> **{DEMO_BANNER}**" in md and "| Database | `jobmarket_test` |" in md
        with engine.connect() as conn:
            for view in employers.VIEWS:
                n = conn.execute(text(f"select count(*) from {view}")).scalar_one()
                assert f"| Rows in `{view}` | {n:,} |" in md
        assert "LCA data not loaded" not in md and "FY2024–FY2026" in md
        assert not re.search(r"\bnan\b", md, re.IGNORECASE) and not re.search(r"\bNone\b", md)
        assert "redirect" not in md.lower() and "http" not in md

        with engine.begin() as conn:
            conn.execute(text("truncate lca_cases"))
        assert main([employers.SLUG, "--out", str(tmp_path / "without")]) == 0
        md = (tmp_path / "without" / employers.SLUG / "report.md").read_text()
        assert md.count("**LCA data not loaded.**") == 3
        assert "## 2. Who posts analyst jobs" in md and "| #1 |" in md
    finally:
        engine.dispose()
        import src.utils.db as dbmod

        dbmod._engine = None
        dbmod._SessionFactory = None
