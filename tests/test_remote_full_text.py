"""A3: remote detection reads the fullest text available."""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select

from src.cleaning.apply_cleaning import apply_remote
from src.cleaning.remote import detect_remote
from src.ingestion.usajobs_parser import parse_job
from src.models import Job
from src.utils.db import session_scope
from tests.conftest import reset_schema

FIXTURES = Path(__file__).parent / "fixtures"
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
needs_db = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set"),
]


# --- federal telework phrasing: situational / ad-hoc telework is not remote ---


@pytest.mark.parametrize(
    "text",
    [
        "Telework eligible: Yes, as determined by agency policy.",
        "Telework: Ad hoc",
        "Telework: Ad hoc per agency policy",
        "This position is eligible for ad-hoc telework.",
        "This position may be authorized for telework.",
        "Telework eligibility will be discussed during the interview process.",
        "Situational telework may be approved by the supervisor.",
        "Eligible for situational telecommuting.",
        "Ad hoc telecommuting is available.",
        "Occasional telework is permitted.",
        "Episodic telecommuting per agency policy.",
    ],
)
def test_federal_telework_boilerplate_is_not_remote(text):
    assert detect_remote("Program Analyst", None, text) is False


def test_plain_telecommuting_still_counts_as_remote():
    # unchanged rule: telecommuting without a situational qualifier is a
    # positive signal
    assert detect_remote("Analyst", None, "This is a telecommuting position.") is True


def test_fixture_postings_none_flip_to_remote():
    """The USAJobs sample: reading description_full flips no posting."""
    items = json.loads((FIXTURES / "usajobs_sample_response.json").read_text())["SearchResult"][
        "SearchResultItems"
    ]
    flips = []
    for item in items:
        j = parse_job(item)
        before = detect_remote(j["title"], None, j["description"])
        after = detect_remote(j["title"], None, j["description_full"] or j["description"])
        if before != after:
            flips.append(j["external_id"])
    assert len(items) == 25
    assert flips == []


# --- apply_remote: full text for USAJobs, commercial unchanged -------------


@pytest.fixture()
def engine():
    eng = create_engine(TEST_DB_URL)
    reset_schema(eng)
    yield eng
    eng.dispose()


COMMERCIAL = [
    ("c1", "Data Analyst", "Fully remote team, work from home."),
    ("c2", "Remote Data Analyst", "Hybrid schedule in NYC."),
    ("c3", "Data Analyst", "Hybrid, but remote-friendly culture."),
    ("c4", "Data Analyst", "This is not a remote position."),
    ("c5", "Data Analyst", None),
    ("c6", "Data Analyst", "SQL and Excel."),
]


@pytest.mark.parametrize("_", [None], ids=["db"])
@pytest.mark.integration
@pytest.mark.skipif(not TEST_DB_URL, reason="TEST_DATABASE_URL not set")
def test_apply_remote_full_text_and_commercial_unchanged(engine, _):
    with session_scope(TEST_DB_URL) as s:
        for ext, title, desc in COMMERCIAL:
            s.add(Job(external_id=ext, source="adzuna", title=title, description=desc))
        s.add(
            Job(
                external_id="f-full",
                source="usajobs",
                title="Program Analyst",
                description="Summary with no telework text.",
                description_full="Summary.\n\nThis is a fully remote position.",
            )
        )
        s.add(
            Job(
                external_id="f-adhoc",
                source="usajobs",
                title="Program Analyst",
                description="Summary.",
                description_full="Summary.\n\nTelework: Ad hoc. Work from home on occasion.",
            )
        )
    with session_scope(TEST_DB_URL) as s:
        apply_remote(s)
    with session_scope(TEST_DB_URL) as s:
        got = dict(s.execute(select(Job.external_id, Job.is_remote)).all())
    # commercial rows: exactly what the pre-A3 call (title, None, description) gives
    for ext, title, desc in COMMERCIAL:
        assert got[ext] is detect_remote(title, None, desc), ext
    assert got["f-full"] is True  # was False when only `description` was read
    assert got["f-adhoc"] is False


def test_ad_hoc_label_beats_a_positive_phrase():
    text = "Telework: Ad hoc. Work from home on occasion."
    assert detect_remote("Program Analyst", None, text) is False
