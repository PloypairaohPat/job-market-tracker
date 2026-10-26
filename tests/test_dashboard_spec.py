"""Dashboard specs (dashboards/*.json + dashboards/sql/*.sql) and their validator."""

import json
import os
import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from scripts.seed_demo_data import seed_full
from src.dashboard.reader_role import grant_reader
from src.dashboard.spec import (
    GRID_COLUMNS,
    card_sql,
    load_and_validate,
    load_dashboards,
    referenced_relations,
    validate,
)
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

SALARY_CAVEAT_OK = (
    "SELECT salary_is_predicted, COUNT(*) AS n FROM v_commercial_salary_clean "
    "GROUP BY salary_is_predicted"
)
TRUNC = "Commercial text is truncated at about 500 characters."


# --------------------------------------------------------------------- #
# helpers: a one-dashboard spec directory


def question(key, sql_file=None, **kw):
    card = {
        "key": key,
        "type": "question",
        "title": kw.pop("title", f"Card {key}"),
        "sql": sql_file or f"{key}.sql",
        "display": "table",
        "description": kw.pop("description", "A described card."),
        "position": {"col": kw.pop("col", 0), "row": kw.pop("row", 0)},
        "size": {"x": kw.pop("x", 6), "y": kw.pop("y", 4)},
        "visualization_settings": {},
    }
    card.update(kw)
    return card


def make_spec(tmp_path, cards, sql: dict[str, str], extra_dashboards=None):
    (tmp_path / "sql").mkdir(exist_ok=True)
    for name, body in sql.items():
        (tmp_path / "sql" / name).write_text(body)
    spec = {"name": "Test", "description": "d", "public": True, "cards": cards}
    (tmp_path / "test.json").write_text(json.dumps(spec))
    for slug, cards2 in (extra_dashboards or {}).items():
        (tmp_path / f"{slug}.json").write_text(json.dumps({**spec, "cards": cards2}))
    return validate(load_dashboards(tmp_path), tmp_path)


def errors_for(tmp_path, sql, **kw):
    return make_spec(tmp_path, [question("c1", **kw)], {"c1.sql": sql})


# --------------------------------------------------------------------- #
# the committed specs


def test_committed_specs_are_valid():
    dashboards = load_and_validate()
    assert {d.slug for d in dashboards} == {
        "ingestion-health",
        "market-overview",
        "salary",
        "skills",
        "transparency",
        "visa-outlook",
    }
    public = {d.slug: d.public for d in dashboards}
    assert public["visa-outlook"] is False
    assert all(v for k, v in public.items() if k != "visa-outlook")
    for d in dashboards:
        # each dashboard opens with a text card naming its sources, plus a data-window card
        first = sorted(d.cards, key=lambda c: (c.row, c.col))[:2]
        assert first[0].type == "text" and "source" in first[0].text.lower()
        assert first[1].key.endswith("_window")


# --------------------------------------------------------------------- #
# relation parsing


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("select * from v_a", {"v_a"}),
        ("select * from public.v_a a join v_b b on a.x = b.x", {"v_a", "v_b"}),
        ('select * from "jobs"', {"jobs"}),
        ("select * from v_a a, jobs j", {"v_a", "jobs"}),
        ("select * from v_a left join raw_responses r on true", {"v_a", "raw_responses"}),
        ("with jobs as (select 1 from v_a) select * from jobs", {"v_a"}),  # CTE shadows
        ("with x as (select 1), y as (select 2 from v_b) select * from x, y", {"v_b"}),
        ("select extract(year from snapshot_date) from v_a", {"v_a"}),
        ("select generate_series(1, 3) from v_a", {"v_a"}),
        ("select * from generate_series(1, 3) g, v_a", {"v_a"}),
        ("select * from (select * from lca_cases) s", {"lca_cases"}),
        ("-- from jobs\nselect 'from jobs' from v_a", {"v_a"}),  # comments and strings ignored
    ],
)
def test_referenced_relations(sql, expected):
    assert referenced_relations(sql) == expected


# --------------------------------------------------------------------- #
# one test per rule


def test_rule_non_view_relation(tmp_path):
    errs = errors_for(
        tmp_path, "select count(*) as n from v_market_jobs m join jobs j on j.id = m.job_id"
    )
    assert any("reads 'jobs'" in e for e in errs)
    assert errors_for(tmp_path, "select count(*) as n from v_market_jobs") == []


def test_rule_missing_description(tmp_path):
    errs = errors_for(tmp_path, "select 1 as n from v_a", description="  ")
    assert any("no description" in e for e in errs)


@pytest.mark.parametrize(
    "sql,ok",
    [
        ("select avg(salary_midpoint) as m, count(*) as n from v_commercial_salary_clean", False),
        (
            "select count(*) as n from v_commercial_salary_clean where salary_is_predicted = false",
            True,
        ),
        ("select count(*) as n from v_commercial_salary_clean where not salary_is_predicted", True),
        (SALARY_CAVEAT_OK, True),
        # the split must name the column: positional GROUP BY isn't resolved
        (
            "select salary_is_predicted, count(*) as n from v_commercial_salary_clean group by 1",
            False,
        ),
        # mentioning the column elsewhere doesn't count
        ("select salary_is_predicted, salary_midpoint from v_commercial_salary_clean", False),
    ],
)
def test_rule_salary_never_blends_predicted_and_disclosed(tmp_path, sql, ok):
    errs = errors_for(tmp_path, sql)
    assert (not any("salary_is_predicted" in e for e in errs)) is ok, errs


def test_rule_skills_cards_carry_the_truncation_caveat(tmp_path):
    sql = "select name, n_jobs_tagged from v_skill_top_by_source"
    assert any("truncation" in e for e in errors_for(tmp_path, sql, description="Top skills."))
    assert errors_for(tmp_path, sql, description=f"Top skills. {TRUNC}") == []


@pytest.mark.parametrize(
    "field",
    ["pct_seniority_present", "pct_metro_present", "pct_remote_true", "metro_area", "seniority"],
)
def test_rule_instrument_limited_fields_are_labelled(tmp_path, field):
    sql = f"select market, n_jobs, {field} from v_field_completeness"
    assert any("instrument-limited" in e for e in errors_for(tmp_path, sql))
    labelled = errors_for(tmp_path, sql, title=f"{field} (instrument-limited)")
    assert labelled == []


def test_rule_grid_overlap_and_width(tmp_path):
    sql = {"a.sql": "select 1 as n from v_a", "b.sql": "select 1 as n from v_a"}
    overlap = make_spec(
        tmp_path,
        [question("a", col=0, row=0, x=12, y=4), question("b", col=6, row=2, x=12, y=4)],
        sql,
    )
    assert any("overlap" in e for e in overlap)
    touching = make_spec(
        tmp_path,
        [question("a", col=0, row=0, x=12, y=4), question("b", col=12, row=0, x=12, y=4)],
        sql,
    )
    assert touching == []
    off_grid = make_spec(
        tmp_path, [question("a", col=GRID_COLUMNS - 4, x=6)], {"a.sql": sql["a.sql"]}
    )
    assert any(f"{GRID_COLUMNS}-column grid" in e for e in off_grid)


def test_rule_missing_sql_file(tmp_path):
    errs = make_spec(tmp_path, [question("a", sql_file="nope.sql")], {})
    assert any("missing SQL file" in e for e in errs)


def test_rule_duplicate_keys_across_dashboards(tmp_path):
    errs = make_spec(
        tmp_path,
        [question("a")],
        {"a.sql": "select 1 as n from v_a"},
        extra_dashboards={"other": [question("a")]},
    )
    assert any("duplicate card key" in e for e in errs)


# --------------------------------------------------------------------- #
# every card runs as the reader role on the full demo data

READER = "jmt_test_dashboard_reader"
READER_PASSWORD = "demo-only-not-secret"
_AGGREGATE = re.compile(
    r"\bgroup\s+by\b|\b(?:count|sum|avg|min|max|percentile_cont|mode|string_agg)\s*\(", re.I
)


@pytest.fixture(scope="module")
def reader_engine(tmp_path_factory):
    if not TEST_DB_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    owner = create_engine(TEST_DB_URL)
    reset_schema(owner)
    seed_full(TEST_DB_URL, candidates_out=tmp_path_factory.mktemp("spec") / "c.csv")
    grant_reader(TEST_DB_URL, READER_PASSWORD, role=READER)
    url = make_url(TEST_DB_URL).set(username=READER, password=READER_PASSWORD)
    reader = create_engine(url)
    yield reader
    reader.dispose()
    with owner.begin() as conn:
        conn.execute(text(f'drop owned by "{READER}"'))
        conn.execute(text(f'drop role "{READER}"'))
    owner.dispose()
    import src.utils.db as dbmod

    dbmod._engine = None
    dbmod._SessionFactory = None


QUESTION_CARDS = [(d.slug, c) for d in load_dashboards() for c in d.cards if c.is_question]


@pytest.mark.integration
@pytest.mark.parametrize("slug,card", QUESTION_CARDS, ids=[c.key for _, c in QUESTION_CARDS])
def test_card_runs_as_reader_on_demo_data(reader_engine, slug, card):
    sql = card_sql(card)
    with reader_engine.connect() as conn:
        result = conn.execute(text(sql.replace(":", r"\:")))
        columns = list(result.keys())
        rows = result.all()
    assert rows, f"{slug}/{card.key} returned no rows on the demo data"
    if _AGGREGATE.search(sql):
        assert any(c == "n" or c.startswith("n_") for c in columns), (
            f"{slug}/{card.key} aggregates but returns no n column: {columns}"
        )
