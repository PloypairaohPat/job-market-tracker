"""Unit tests for src/ingestion/adzuna_parser.py — pure functions, no I/O."""

import json
from datetime import UTC
from pathlib import Path

import pytest

from src.ingestion import adzuna_parser as p

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def page() -> dict:
    return json.loads((FIXTURES / "adzuna_page_1.json").read_text())


def test_fixture_has_expected_shape(page):
    assert "count" in page and "results" in page
    assert len(page["results"]) == 50


def test_parse_job_core_fields(page):
    job = p.parse_job(page["results"][0])
    assert job["source"] == "adzuna"
    assert job["external_id"]
    assert job["title"]
    assert job["title_normalized"] == job["title_normalized"].lower()


def test_parse_job_requires_id():
    with pytest.raises(KeyError):
        p.parse_job({"title": "Data Analyst"})


def test_normalize_title_lowercases_and_collapses_whitespace():
    assert p.normalize_title("  Senior   Data\tAnalyst ") == "senior data analyst"


def test_parse_created_iso_z_suffix():
    dt = p.parse_created("2026-06-28T04:12:33Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.astimezone(UTC).hour == 4


def test_parse_created_garbage_returns_none():
    assert p.parse_created("not-a-date") is None
    assert p.parse_created(None) is None
    assert p.parse_created("") is None


def test_salary_fields_flag_not_guess():
    """Missing salary -> all salary fields None (flag, don't guess)."""
    job = p.parse_job({"id": "1", "title": "Data Analyst"})
    assert job["salary_min"] is None
    assert job["salary_max"] is None
    assert job["salary_currency"] is None
    assert job["salary_period"] is None


def test_salary_present_sets_currency_and_period():
    job = p.parse_job({"id": "1", "title": "x", "salary_min": 75000.0, "salary_max": 95000.0})
    assert job["salary_min"] == 75000
    assert job["salary_max"] == 95000
    assert job["salary_currency"] == "USD"
    assert job["salary_period"] == "year"


def test_salary_is_predicted_string_coercion():
    assert (
        p.parse_job({"id": "1", "title": "x", "salary_is_predicted": "1"})["salary_is_predicted"]
        is True
    )
    assert (
        p.parse_job({"id": "1", "title": "x", "salary_is_predicted": "0"})["salary_is_predicted"]
        is False
    )
    assert p.parse_job({"id": "1", "title": "x"})["salary_is_predicted"] is None


def test_parse_company_missing_returns_none():
    assert p.parse_company({"id": "1"}) is None
    assert p.parse_company({"id": "1", "company": {}}) is None
    assert p.parse_company({"id": "1", "company": {"display_name": "   "}}) is None


def test_parse_company_records_raw_name():
    c = p.parse_company({"company": {"display_name": "Meta Platforms Inc"}})
    assert c == {"canonical_name": "Meta Platforms Inc", "raw_names": ["Meta Platforms Inc"]}


def test_parse_location_full_hierarchy():
    loc = p.parse_location({"location": {"area": ["US", "Virginia", "Fairfax County", "Fairfax"]}})
    assert loc["country"] == "US"
    assert loc["state"] == "Virginia"
    assert loc["city"] == "Fairfax"


def test_parse_location_state_only():
    loc = p.parse_location({"location": {"area": ["US", "Virginia"]}})
    assert loc["country"] == "US"
    assert loc["state"] == "Virginia"
    assert loc["city"] is None


def test_parse_location_country_only_and_missing():
    loc = p.parse_location({"location": {"area": ["US"]}})
    assert loc["country"] == "US" and loc["state"] is None and loc["city"] is None
    assert p.parse_location({}) is None
    assert p.parse_location({"location": {"area": []}}) is None


def test_detect_remote_title_and_location():
    assert p.detect_remote({"title": "Data Analyst - Remote"}) is True
    assert (
        p.detect_remote({"title": "Data Analyst", "location": {"display_name": "Remote, US"}})
        is True
    )
    assert (
        p.detect_remote({"title": "Data Analyst", "location": {"display_name": "Fairfax, VA"}})
        is False
    )
    # word-boundary: 'remote' inside another word must not match
    assert p.detect_remote({"title": "Remotely Sensed Imagery Analyst"}) is False


def test_every_fixture_job_parses(page):
    """No result in the 50-job fixture should raise."""
    for raw in page["results"]:
        job = p.parse_job(raw)
        assert job["external_id"]
