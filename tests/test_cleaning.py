"""Unit tests for the Phase 2 cleaning modules.

Same philosophy as the skill extractor tests: every judgment call and
ambiguity documented in a module gets an executable trap case here.
"""

import pytest

from src.cleaning.company_normalizer import find_merge_candidates, normalize_company_name
from src.cleaning.metro import assign_metro
from src.cleaning.remote import detect_remote
from src.cleaning.salary_quality import assess_salary_quality
from src.cleaning.seniority import classify_seniority

# ------------------------------------------------------------------ #
# seniority


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Data Analyst", "senior"),
        ("Sr. Data Analyst (Hybrid)", "senior"),
        ("Data Analyst III", "senior"),
        ("Lead Data Analyst", "lead"),
        ("Principal Analytics Engineer", "lead"),
        ("Analytics Manager", "lead"),
        ("Head of Business Intelligence", "lead"),
        ("Associate Director, Analytics", "lead"),  # the associate trap
        ("Junior Data Analyst", "junior"),
        ("Data Analyst I", "junior"),
        ("Entry Level Data Analyst", "junior"),
        ("Associate Data Analyst", "junior"),
        ("Data Analyst II", "mid"),
        ("Mid-Level BI Analyst", "mid"),
        ("Data Analyst", None),  # no signal -> None, never 'mid'
        ("Business Intelligence Analyst", None),
        ("Senior Lead Analyst", "lead"),  # precedence: lead > senior
        (None, None),
        ("", None),
    ],
)
def test_classify_seniority(title, expected):
    assert classify_seniority(title) == expected


# ------------------------------------------------------------------ #
# salary quality


@pytest.mark.parametrize(
    ("smin", "smax", "period", "expected"),
    [
        (None, None, None, None),  # nothing disclosed -> nothing to assess
        (75_000, 95_000, "year", "ok"),
        (95_000, 75_000, "year", "suspect_inverted"),
        (18, 28, "year", "suspect_hourly_as_annual"),  # the classic contamination
        (20_000, 24_000, "year", "suspect_hourly_as_annual"),
        (25_000, 30_000, "year", "ok"),  # boundary: ceiling is exclusive
        (600_000, 900_000, "year", "suspect_outlier_high"),
        (75_000, None, "year", "ok"),  # single-sided values still assessable
        (None, 15_000, "year", "suspect_hourly_as_annual"),
        (18, 28, "hour", "ok"),  # hourly period declared -> low values are fine
    ],
)
def test_assess_salary_quality(smin, smax, period, expected):
    assert assess_salary_quality(smin, smax, period) == expected


# ------------------------------------------------------------------ #
# metro


@pytest.mark.parametrize(
    ("city", "state", "expected"),
    [
        ("New York", "New York", "NYC"),
        ("Brooklyn", "New York", "NYC"),
        ("San Francisco", "California", "SF Bay Area"),
        ("Palo Alto", "California", "SF Bay Area"),
        ("Fairfax", "Virginia", "DC"),
        ("Arlington", "Virginia", "DC"),
        ("Washington", "District Of Columbia", "DC"),
        ("Washington", "Washington", None),  # the state-collision trap
        ("Seattle", "Washington", "Seattle"),
        ("Springfield", "Virginia", "DC"),
        ("Springfield", "Illinois", None),  # many Springfields; only VA claimed
        ("Austin", "Texas", "Austin"),
        ("Boise", "Idaho", None),  # untracked metro -> None
        (None, "Virginia", None),
        ("", None, None),
    ],
)
def test_assign_metro(city, state, expected):
    assert assign_metro(city, state) == expected


# ------------------------------------------------------------------ #
# remote


def test_remote_title_signal_is_strong():
    assert detect_remote("Data Analyst - Remote", None, "hybrid schedule available") is True


def test_remote_location_display_signal():
    assert detect_remote("Data Analyst", "Remote, US", None) is True


def test_remote_description_positive():
    assert detect_remote("Data Analyst", None, "This is a fully remote position.") is True
    assert detect_remote("Data Analyst", None, "Work from home with quarterly onsites.") is True


def test_hybrid_is_not_remote():
    assert (
        detect_remote("Data Analyst", None, "Hybrid: 3 days in office, remote work Fridays.")
        is False
    )


def test_negation_blocks_description_positive():
    assert (
        detect_remote("Data Analyst", None, "This is not a remote position. Onsite only.") is False
    )
    assert detect_remote("Data Analyst", None, "No remote work. Must be on-site.") is False


def test_no_signal_is_false():
    assert detect_remote("Data Analyst", None, "Great team in our downtown office.") is False
    assert detect_remote(None, None, None) is False


# ------------------------------------------------------------------ #
# company normalization


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Meta", "meta"),
        ("Meta Platforms Inc", "meta"),
        ("Facebook", "meta"),
        ("FB", "meta"),
        ("Deloitte", "deloitte"),
        ("Deloitte Consulting LLP", "deloitte"),
        ("Amazon.com", "amazon"),
        ("The Home Depot, Inc.", "home depot"),
        ("Acme Holdings LLC", "acme"),  # iterative suffix stripping
        ("Booz Allen Hamilton", "booz allen hamilton"),
        ("CVS Health", "cvs health"),
        ("Capital One", "capital one"),
        ("TekSystems", "teksystems"),
        ("  Robert   Half  ", "robert half"),  # whitespace hygiene
    ],
)
def test_normalize_company_name(raw, expected):
    assert normalize_company_name(raw) == expected


def test_normalization_is_idempotent():
    for raw in ("Meta Platforms Inc", "The Home Depot, Inc.", "Deloitte Consulting LLP"):
        once = normalize_company_name(raw)
        assert normalize_company_name(once) == once


def test_merge_candidates_containment_and_fuzzy():
    names = [
        "capital one",
        "capital one financial",  # containment
        "booz allen hamilton",
        "booz allen hamiltn",  # typo -> fuzzy
        "meta",
        "geico",  # unrelated
    ]
    cands = find_merge_candidates(names)
    relations = {(c["name_a"], c["name_b"]): c["relation"] for c in cands}
    assert relations[("capital one", "capital one financial")] == "containment"
    assert relations[("booz allen hamiltn", "booz allen hamilton")] == "fuzzy"
    assert not any("meta" in pair or "geico" in pair for pair in relations)


def test_merge_candidates_never_auto_apply():
    """The candidates API returns proposals only — it must not mutate input."""
    names = ["capital one", "capital one financial"]
    find_merge_candidates(names)
    assert names == ["capital one", "capital one financial"]
