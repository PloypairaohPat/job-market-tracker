"""Report 1, commercial vs federal skill demand (src/reports/skill_demand.py).

- A golden file: the report rendered from hand-built view frames (invented
  numbers) must match tests/fixtures/reports/commercial-vs-federal-skills.md.
  After an intended change, regenerate it with UPDATE_GOLDEN=1 and review the diff.
- The module's constants agree with the view SQL and the taxonomy.
- End to end on the full demo seed, through the CLI.
"""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from scripts.seed_demo_data import seed_full
from src.reports import skill_demand
from src.reports.__main__ import main
from src.reports.guardrails import GuardrailError
from src.reports.provenance import DEMO_BANNER, Provenance
from src.reports.views import VIEWS_DIR, repo_views
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
GOLDEN = Path(__file__).parent / "fixtures" / "reports" / f"{skill_demand.SLUG}.md"
REPO = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------- #
# hand-built view frames (invented numbers, shaped like the real views)


def frames(**overrides) -> dict[str, pd.DataFrame]:
    basis = pd.DataFrame(
        [
            ("commercial", 400, 0, 396, 497.0, 500.0, 503.0, 180, 300),
            ("federal", 40, 40, 0, 4000.0, 6000.0, 8000.0, 39, 120),
        ],
        columns=[
            "market",
            "n_jobs",
            "n_full_text",
            "n_near_cap",
            "p25_text_chars",
            "median_text_chars",
            "p75_text_chars",
            "n_jobs_tagged",
            "n_tags",
        ],
    )
    composition = pd.DataFrame(
        [
            ("commercial", "workflow", 100, 33.3, 400),
            ("commercial", "bi_tool", 80, 26.7, 400),
            ("commercial", "language", 60, 20.0, 400),
            ("commercial", "ml_stats", 40, 13.3, 400),
            ("commercial", "cloud", 12, 4.0, 400),
            ("commercial", "data_tool", 8, 2.7, 400),
            ("federal", "ml_stats", 48, 40.0, 40),
            ("federal", "language", 36, 30.0, 40),
            ("federal", "bi_tool", 20, 16.7, 40),
            ("federal", "workflow", 12, 10.0, 40),
            ("federal", "database", 4, 3.3, 40),
        ],
        columns=["market", "category", "n_tags", "pct_of_tags", "market_n_jobs"],
    )
    top = pd.DataFrame(
        [
            ("commercial", "SQL", "language", 60, 400, 15.0),
            ("commercial", "Tableau", "bi_tool", 45, 400, 11.3),
            ("commercial", "Python", "language", 15, 400, 3.8),
            ("commercial", "Excel", "bi_tool", 14, 400, 3.5),
            ("federal", "Statistics", "ml_stats", 30, 40, 75.0),
            ("federal", "Python", "language", 20, 40, 50.0),
            ("federal", "SPSS", "language", 6, 40, 15.0),
            ("federal", "SQL", "language", 5, 40, 12.5),
            ("federal", "GIS", "data_tool", 4, 40, 10.0),
        ],
        columns=["market", "name", "category", "n_jobs_tagged", "market_n_jobs", "pct_of_jobs"],
    )
    admission = pd.DataFrame(
        [
            ("series:Operations Research", "Statistics", "ml_stats", 12, 14, 85.7),
            ("series:Operations Research", "Python", "language", 5, 14, 35.7),
            ("series:Statistics", "Statistics", "ml_stats", 15, 16, 93.8),
            (
                "skill_density:Management And Program Analysis",
                "Statistics",
                "ml_stats",
                3,
                10,
                30.0,
            ),
        ],
        columns=[
            "admission_route",
            "name",
            "category",
            "n_jobs_tagged",
            "route_n_jobs",
            "pct_of_jobs",
        ],
    )
    out = {
        "v_skill_text_basis": basis,
        "v_skill_category_composition": composition,
        "v_skill_top_by_source": top,
        "v_federal_skill_by_admission": admission,
    }
    out.update(overrides)
    return out


def stamp(database="jobmarket_test_golden"):
    return Provenance(
        database=database,
        generated_at=datetime(2026, 10, 27, 3, 0, tzinfo=UTC),
        git_commit="golden000000",
        view_rows={v: 0 for v in skill_demand.VIEWS},
    )


def test_the_report_matches_its_golden_file(tmp_path):
    path = skill_demand.render(skill_demand.compute(frames()), stamp(), tmp_path)
    rendered = path.read_text()
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(rendered)
    assert rendered == GOLDEN.read_text()
    assert (path.parent / "composition.png").stat().st_size > 10_000


def test_floors_flags_and_rounding_in_the_rendered_report(tmp_path):
    md = skill_demand.render(skill_demand.compute(frames()), stamp(), tmp_path).read_text()
    assert md.index(DEMO_BANNER) < md.index("# Commercial vs federal skill demand")
    # drill-down: Excel (14 < 15) and GIS (4 < 5) suppressed and counted
    assert "| Excel |" not in md and "| GIS † |" not in md
    assert "1 more commercial skill(s) below n ≥ 15 are not shown." in md
    assert "1 more federal skill(s) below n ≥ 5 are not shown." in md
    # Postgres-style rounding of the view's own percentage, never re-derived
    assert "| Tableau | bi_tool | 11.3% (45 of 400 jobs) |" in md
    assert "| Statistics | ml_stats | 75.0% (30 of 40 jobs) |" in md
    # composition: a category one market lacks is 0 of its tags, and flagged
    assert "| database | 0.0% (0 of 300 tags) | 3.3% (4 of 120 tags) | -3.3 pp |" in md
    assert "Here: commercial cloud, commercial data_tool, commercial database" in md
    # federal-fitted taxonomy entries are marked
    assert "| SPSS † | language | 15.0% (6 of 40 jobs) |" in md
    # narrative is placeholders only, each with numbers
    for section in ("Headline", "What it means", "What to do about it"):
        assert f"**[TO WRITE: {section}]**" in md
    assert "> - Commercial workflow + bi_tool combined: 60.0% (180 of 300 tags)" in md
    assert "> - Statistics-tagged in series:Operations Research: 85.7% (12 of 14 jobs)" in md


def test_a_composition_rate_against_the_wrong_denominator_is_refused():
    bad_basis = frames()["v_skill_text_basis"].assign(n_tags=[400, 120])  # 300 tags really
    with pytest.raises(GuardrailError, match="wrong denominator"):
        skill_demand.compute(frames(v_skill_text_basis=bad_basis))


def test_a_market_with_no_rows_renders_as_not_applicable(tmp_path):
    only_commercial = {
        name: frame[frame.iloc[:, 0] != "federal"] if "market" in frame else frame.iloc[0:0]
        for name, frame in frames().items()
    }
    md = skill_demand.render(skill_demand.compute(only_commercial), stamp(), tmp_path).read_text()
    assert "| federal | 0 | n/a (0 of 0 jobs) |" in md
    assert "No federal skill reaches the n ≥ 5 floor." in md
    assert "No federal in-scope jobs in this data." in md


# --------------------------------------------------------------------- #
# the module's constants agree with the views and the taxonomy


def _sql_body(view: str) -> str:
    return re.sub(r"--[^\n]*", "", (VIEWS_DIR / f"{view}.sql").read_text())


def test_constants_match_the_view_sql():
    assert set(skill_demand.VIEWS) <= repo_views()
    for view in skill_demand.VIEWS:
        thresholds = re.findall(r"confidence\s*>=\s*([\d.]+)", _sql_body(view))
        assert thresholds and {float(t) for t in thresholds} == {skill_demand.SKILL_CONFIDENCE}
    assert f">= {skill_demand.NEAR_CAP_CHARS}" in _sql_body("v_skill_text_basis")


def test_federal_fitted_entries_exist_in_the_taxonomy():
    taxonomy = json.loads((REPO / "src/cleaning/data/skills.json").read_text())["skills"]
    by_name = {s["name"]: s for s in taxonomy}
    assert set(skill_demand.FEDERAL_FITTED) <= set(by_name)
    assert "structured query language" in by_name["SQL"]["aliases"]


def test_reports_touch_the_database_only_through_the_view_reader():
    for path in (REPO / "src" / "reports").glob("*.py"):
        if path.name == "views.py":
            continue
        source = path.read_text()
        for forbidden in ("read_sql", ".execute(", "from sqlalchemy import text"):
            assert forbidden not in source, f"{path.name} uses {forbidden}"


# --------------------------------------------------------------------- #
# end to end on the full demo seed


@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_end_to_end_on_the_demo_seed(tmp_path, monkeypatch, capsys):
    engine = create_engine(TEST_DB_URL)
    reset_schema(engine)
    seed_full(TEST_DB_URL, candidates_out=tmp_path / "c.csv")
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    try:
        assert main([skill_demand.SLUG, "--out", str(tmp_path / "out")]) == 0
        md = (tmp_path / "out" / skill_demand.SLUG / "report.md").read_text()
        assert f"> **{DEMO_BANNER}**" in md
        assert "| Database | `jobmarket_test` |" in md
        with engine.connect() as conn:
            for view in skill_demand.VIEWS:
                n = conn.execute(text(f"select count(*) from {view}")).scalar_one()
                assert f"| Rows in `{view}` | {n:,} |" in md
        assert (tmp_path / "out" / skill_demand.SLUG / "composition.png").exists()
        assert not re.search(r"\bnan\b|\bNone\b", md, re.IGNORECASE)
        assert "wrote " in capsys.readouterr().out
    finally:
        engine.dispose()
        import src.utils.db as dbmod

        dbmod._engine = None
        dbmod._SessionFactory = None


def test_the_cli_lists_reports(capsys):
    assert main(["--list"]) == 0
    assert skill_demand.SLUG in capsys.readouterr().out


def test_an_unwritable_output_directory_is_a_clean_error(monkeypatch, capsys):
    import src.reports.__main__ as cli

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied", "/reports/x")

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@127.0.0.1:5432/jobmarket_test")
    monkeypatch.setattr(cli, "generate", refuse)
    assert cli.main([skill_demand.SLUG, "--out", "/reports"]) == 1
    assert "report not written to /reports" in capsys.readouterr().err
