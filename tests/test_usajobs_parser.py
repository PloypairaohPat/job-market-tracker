"""Unit tests for src/ingestion/usajobs_parser.py — pure functions, no I/O."""

import json
from datetime import UTC
from pathlib import Path

import pytest

from src.ingestion import usajobs_parser as p

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def page() -> dict:
    return json.loads((FIXTURES / "usajobs_sample_response.json").read_text())


@pytest.fixture(scope="module")
def items(page) -> list[dict]:
    return page["SearchResult"]["SearchResultItems"]


def test_fixture_has_expected_shape(page):
    assert "SearchResult" in page
    sr = page["SearchResult"]
    assert "SearchResultItems" in sr and "SearchResultCountAll" in sr
    assert len(sr["SearchResultItems"]) == 25


def test_parse_job_core_fields(items):
    job = p.parse_job(items[0])
    assert job["source"] == "usajobs"
    assert job["external_id"] == "880660900"
    assert job["title"] == "Data Analyst"
    assert job["title_normalized"] == "data analyst"


def test_external_id_uses_matched_object_id_not_position_id(items):
    """PositionID (e.g. 'FD-2026-0027') is the agency's own announcement
    number, not guaranteed unique across agencies -- MatchedObjectId is
    USAJobs' own system key and is what we key on."""
    raw = items[0]
    job = p.parse_job(raw)
    assert job["external_id"] == str(raw["MatchedObjectId"])
    assert job["external_id"] != raw["MatchedObjectDescriptor"]["PositionID"]


def test_parse_job_requires_matched_object_id():
    with pytest.raises(KeyError):
        p.parse_job({"MatchedObjectDescriptor": {"PositionTitle": "Data Analyst"}})


def test_description_and_description_full_are_not_truncated(items):
    """Confirms the whole point of adding USAJobs: no 500-char cap."""
    for raw in items:
        job = p.parse_job(raw)
        if job["description_full"]:
            assert len(job["description_full"]) > 500
        # never a hard cap at exactly 500 with a truncation marker
        assert not (job["description"] or "").endswith("…")


def test_description_full_excludes_process_boilerplate(items):
    """Narrative-only composition: HowToApply text should not leak in."""
    raw = items[0]
    details = raw["MatchedObjectDescriptor"]["UserArea"]["Details"]
    how_to_apply = details.get("HowToApply") or ""
    job = p.parse_job(raw)
    assert how_to_apply, "fixture item should have HowToApply text to test against"
    assert how_to_apply not in job["description_full"]


def test_description_full_includes_qualification_summary(items):
    raw = items[0]
    qual_summary = raw["MatchedObjectDescriptor"]["QualificationSummary"]
    job = p.parse_job(raw)
    assert qual_summary in job["description_full"]


def test_salary_parsed_and_coerced_to_int(items):
    job = p.parse_job(items[0])
    assert job["salary_min"] == 106437
    assert job["salary_max"] == 172980
    assert job["salary_currency"] == "USD"
    assert job["salary_period"] == "year"
    assert job["salary_is_predicted"] is False


def test_salary_unmapped_rate_code_leaves_period_none():
    """Flag, don't guess: a real but unmapped code (e.g. biweekly) should
    not be forced into year/hour/month."""
    raw = {
        "MatchedObjectId": "1",
        "MatchedObjectDescriptor": {
            "PositionTitle": "x",
            "PositionRemuneration": [
                {"MinimumRange": "1000", "MaximumRange": "2000", "RateIntervalCode": "BW"}
            ],
        },
    }
    job = p.parse_job(raw)
    assert job["salary_min"] == 1000
    assert job["salary_max"] == 2000
    assert job["salary_period"] is None


def test_salary_missing_flags_not_guesses():
    job = p.parse_job({"MatchedObjectId": "1", "MatchedObjectDescriptor": {"PositionTitle": "x"}})
    assert job["salary_min"] is None
    assert job["salary_max"] is None
    assert job["salary_currency"] is None
    assert job["salary_period"] is None


def test_is_remote_from_remote_indicator():
    raw = {
        "MatchedObjectId": "1",
        "MatchedObjectDescriptor": {
            "PositionTitle": "x",
            "UserArea": {"Details": {"RemoteIndicator": True}},
        },
    }
    assert p.parse_job(raw)["is_remote"] is True
    raw["MatchedObjectDescriptor"]["UserArea"]["Details"]["RemoteIndicator"] = False
    assert p.parse_job(raw)["is_remote"] is False


def test_category_uses_name_falls_back_to_code():
    raw = {
        "MatchedObjectId": "1",
        "MatchedObjectDescriptor": {
            "PositionTitle": "x",
            "JobCategory": [{"Name": "Management And Program Analysis", "Code": "0343"}],
        },
    }
    assert p.parse_job(raw)["category"] == "Management And Program Analysis"

    raw["MatchedObjectDescriptor"]["JobCategory"] = [{"Name": "", "Code": "0343"}]
    assert p.parse_job(raw)["category"] == "0343"


def test_category_joins_all_entries_not_just_first():
    """Real case: job 865002200, 'INTERDISCIPLINARY GENERAL ENGINEER/
    OPERATIONS RESEARCH ANALYST', is tagged both General Engineering and
    Operations Research. Keeping only the first would silently hide a
    genuinely relevant category from anything filtering on it."""
    raw = {
        "MatchedObjectId": "865002200",
        "MatchedObjectDescriptor": {
            "PositionTitle": "INTERDISCIPLINARY GENERAL ENGINEER/OPERATIONS RESEARCH ANALYST",
            "JobCategory": [
                {"Code": "0801", "Name": "General Engineering"},
                {"Code": "1515", "Name": "Operations Research"},
            ],
        },
    }
    category = p.parse_job(raw)["category"]
    assert "General Engineering" in p.split_categories(category)
    assert "Operations Research" in p.split_categories(category)


def test_split_categories_roundtrips_and_handles_none():
    assert p.split_categories(None) == []
    assert p.split_categories("") == []
    assert p.split_categories("Operations Research") == ["Operations Research"]
    assert p.split_categories("General Engineering; Operations Research") == [
        "General Engineering",
        "Operations Research",
    ]


def test_category_dedupes_repeated_labels():
    raw = {
        "MatchedObjectId": "1",
        "MatchedObjectDescriptor": {
            "PositionTitle": "x",
            "JobCategory": [
                {"Name": "Operations Research", "Code": "1515"},
                {"Name": "Operations Research", "Code": "1515"},
            ],
        },
    }
    assert p.parse_job(raw)["category"] == "Operations Research"


def test_contract_time_and_type_from_verified_codes(items):
    job = p.parse_job(items[0])
    assert job["contract_time"] == "full_time"  # PositionSchedule code '1'
    assert job["contract_type"] == "permanent"  # PositionOfferingType code '15317'


def test_contract_time_and_type_unmapped_codes_are_none():
    raw = {
        "MatchedObjectId": "1",
        "MatchedObjectDescriptor": {
            "PositionTitle": "x",
            "PositionSchedule": [{"Name": "", "Code": "3"}],  # Shift work -- unmapped
            "PositionOfferingType": [{"Name": "", "Code": "15318"}],  # Temporary -- unmapped
        },
    }
    job = p.parse_job(raw)
    assert job["contract_time"] is None
    assert job["contract_type"] is None


def test_redirect_url_from_position_uri(items):
    job = p.parse_job(items[0])
    assert job["redirect_url"] == "https://www.usajobs.gov:443/job/880660900"


def test_parse_published_no_timezone_offset_treated_as_utc():
    dt = p.parse_published("2026-08-14T11:17:15.9170")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.astimezone(UTC).hour == 11


def test_parse_published_garbage_returns_none():
    assert p.parse_published("not-a-date") is None
    assert p.parse_published(None) is None
    assert p.parse_published("") is None


def test_parse_company_uses_department_not_organization(items):
    raw = items[0]
    mod = raw["MatchedObjectDescriptor"]
    company = p.parse_company(raw)
    assert company == {
        "canonical_name": mod["DepartmentName"],
        "raw_names": [mod["DepartmentName"]],
    }
    assert company["canonical_name"] != mod["OrganizationName"]


def test_parse_company_missing_returns_none():
    assert p.parse_company({"MatchedObjectDescriptor": {}}) is None
    assert p.parse_company({"MatchedObjectDescriptor": {"DepartmentName": "  "}}) is None


def test_parse_location_single_location(items):
    """item[1] is a single-location posting (Bethesda, Maryland)."""
    raw = items[1]
    loc = p.parse_location(raw)
    assert loc is not None
    assert loc["city"] == "Bethesda"
    assert loc["state"] == "Maryland"
    assert loc["country"] == "United States"
    assert loc["latitude"] == pytest.approx(38.9864)
    assert loc["longitude"] == pytest.approx(-77.0969)


def test_parse_location_multiple_locations_is_none(items):
    """item[0] has 21 locations -- flag, don't guess which one matters."""
    raw = items[0]
    assert len(raw["MatchedObjectDescriptor"]["PositionLocation"]) > 1
    assert p.parse_location(raw) is None


def test_parse_location_zero_locations_is_none():
    raw = {
        "MatchedObjectId": "1",
        "MatchedObjectDescriptor": {"PositionTitle": "x", "PositionLocation": []},
    }
    assert p.parse_location(raw) is None


def test_extract_city_strips_state_suffix():
    assert p._extract_city("Bethesda, Maryland", "Maryland") == "Bethesda"
    # District of Columbia: city name itself contains no comma collision
    assert p._extract_city("Washington, District of Columbia", "District of Columbia") == (
        "Washington"
    )


def test_extract_city_missing_returns_none():
    assert p._extract_city(None, "Maryland") is None
    assert p._extract_city("", "Maryland") is None


def test_every_fixture_job_parses(items):
    """No result in the 25-job fixture should raise."""
    for raw in items:
        job = p.parse_job(raw)
        assert job["external_id"]
