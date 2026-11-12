"""A2: the skills step converges on the extractor's current matches."""

import os

import pytest
from sqlalchemy import create_engine, text

from src.cleaning.extract_skills import (
    count_orphaned_skills,
    extract_for_all_jobs,
    sync_taxonomy,
)
from src.cleaning.skill_extractor import SkillExtractor, load_taxonomy
from src.models import Job
from src.utils.db import session_scope
from tests.conftest import reset_schema

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture()
def engine():
    eng = create_engine(TEST_DB_URL)
    reset_schema(eng)
    yield eng
    eng.dispose()


def add_job(external_id, description, title="Data Analyst", description_full=None):
    with session_scope(TEST_DB_URL) as s:
        s.add(
            Job(
                external_id=external_id,
                source="adzuna",
                title=title,
                description=description,
                description_full=description_full,
            )
        )


def run(extractor=None, min_confidence=0.0):
    with session_scope(TEST_DB_URL) as s:
        ids = sync_taxonomy(s)
        return extract_for_all_jobs(s, ids, min_confidence, extractor=extractor)


def links(engine) -> dict[str, dict[str, float]]:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "select j.external_id, s.name, js.confidence from job_skills js "
                "join jobs j on j.id = js.job_id join skills s on s.id = js.skill_id"
            )
        ).all()
    out: dict[str, dict[str, float]] = {}
    for ext, name, conf in rows:
        out.setdefault(ext, {})[name] = float(conf)
    return out


def test_changed_description_drops_the_old_skill(engine):
    add_job("j1", "Needs Python and Tableau.")
    run()
    assert {"Python", "Tableau"} <= set(links(engine)["j1"])
    with engine.begin() as c:
        c.execute(
            text("update jobs set description = 'Needs Tableau only.' where external_id='j1'")
        )
    run()
    after = links(engine)["j1"]
    assert "Python" not in after
    assert "Tableau" in after


def test_skill_removed_from_taxonomy_loses_links(engine):
    add_job("j1", "Needs Python and Tableau.")
    run()
    full = load_taxonomy()
    without_python = [d for d in full if d.name != "Python"]
    run(extractor=SkillExtractor(without_python))
    after = links(engine)["j1"]
    assert "Python" not in after
    assert "Tableau" in after
    with session_scope(TEST_DB_URL) as s:
        # the skills row is kept (parked question), and counted as orphaned
        assert s.execute(text("select count(*) from skills where name='Python'")).scalar() == 1
        assert count_orphaned_skills(s, without_python) == 1
        assert count_orphaned_skills(s) == 0


def test_second_run_changes_nothing(engine):
    add_job("j1", "Needs Python, SQL and Tableau.")
    add_job("j2", "Excel and Power BI reporting.")
    first = run()
    snap1 = links(engine)
    second = run()
    assert second == first
    assert links(engine) == snap1


def test_job_with_no_text_ends_with_no_links(engine):
    add_job("j1", "Needs Python.")
    run()
    assert links(engine)["j1"]
    with engine.begin() as c:
        c.execute(
            text(
                "update jobs set title = '', description = NULL, description_full = NULL "
                "where external_id='j1'"
            )
        )
    run()
    assert "j1" not in links(engine)


def test_links_below_min_confidence_are_removed(engine):
    add_job("j1", "Needs Python and Tableau.")
    low = [d for d in load_taxonomy() if d.confidence < 1.0]
    assert low, "taxonomy has reduced-confidence skills"
    run()
    run(min_confidence=1.0)
    for conf in links(engine).get("j1", {}).values():
        assert conf >= 1.0
