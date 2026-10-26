"""Table-driven tests for src/visa/posting_signals.py (pure, no database).

Every rule has a trap: a phrase that looks similar and must NOT fire.
"""

import json
from pathlib import Path

import pytest

from src.visa.posting_signals import (
    classify_cap_exempt,
    classify_posting,
    classify_restriction,
    classify_sponsorship,
    detect_opt,
    normalize_text,
    text_coverage,
)

FIXTURES = Path(__file__).parent / "fixtures"


def restriction(text):
    return classify_restriction(normalize_text(text))


def stance(text):
    return classify_sponsorship(normalize_text(text))


# --------------------------------------------------------------------- #
# sponsorship stance

SPONSORSHIP_CASES = [
    # negated sponsorship
    ("We are unable to sponsor visas for this role.", "will_not_sponsor"),
    ("Sponsorship is not available for this position.", "will_not_sponsor"),
    ("We will not sponsor now or in the future.", "will_not_sponsor"),
    ("The company cannot provide visa sponsorship.", "will_not_sponsor"),
    ("This position is not eligible for visa sponsorship.", "will_not_sponsor"),
    ("No H-1B sponsorship.", "will_not_sponsor"),
    ("no visa sponsorship available", "will_not_sponsor"),
    ("Must be authorized to work in the US without sponsorship.", "will_not_sponsor"),
    (
        "Candidates must be authorized to work in the United States now or in the future.",
        "will_not_sponsor",
    ),
    # positive sponsorship
    ("Visa sponsorship available for the right candidate.", "will_sponsor"),
    ("We sponsor H-1B visas.", "will_sponsor"),
    ("we sponsor H1B", "will_sponsor"),
    ("The company is willing to sponsor.", "will_sponsor"),
    # OPT welcome but no H-1B -> still will_not_sponsor
    ("OPT/CPT welcome but no H-1B sponsorship.", "will_not_sponsor"),
    # case and punctuation variants
    ("WE ARE UNABLE TO SPONSOR.", "will_not_sponsor"),
    ("We can’t sponsor work visas.", "will_not_sponsor"),  # curly apostrophe
    ("We won't sponsor h-1b.", "will_not_sponsor"),
    ("VISA   SPONSORSHIP\nAVAILABLE", "will_sponsor"),
    ("We sponsor H 1B.", "will_sponsor"),
    # traps -- must stay none_found
    ("Must be authorized to work in the US.", "none_found"),  # OPT is work authorization
    ("You will partner with an executive sponsor.", "none_found"),
    ("We sponsor local hackathons and meetups.", "none_found"),
    ("Project sponsors rely on our dashboards.", "none_found"),
    ("Will you now or in the future require sponsorship for employment visa status?", "none_found"),
    ("We sponsor H-1B. Sponsorship is not available for interns.", "none_found"),  # conflicting
]


@pytest.mark.parametrize("text,expected", SPONSORSHIP_CASES)
def test_sponsorship_stance(text, expected):
    assert stance(text)[0] == expected


def test_work_authorization_alone_is_recorded_not_inferred():
    value, reason = stance("Must be authorized to work in the US.")
    assert value == "none_found"
    assert "OPT is work authorization" in reason


def test_ambiguous_sponsorship_phrase_gets_ambiguous_reason():
    value, reason = stance("Will you now or in the future require visa sponsorship?")
    assert value == "none_found"
    assert reason.startswith("ambiguous: ")


def test_conflicting_statements_are_ambiguous():
    value, reason = stance("We sponsor H-1B. Sponsorship is not available for interns.")
    assert value == "none_found" and reason.startswith("ambiguous: conflicting")


# --------------------------------------------------------------------- #
# restriction

RESTRICTION_CASES = [
    # citizenship
    ("You must be a U.S. citizen to apply for this job.", "citizenship"),
    ("Must be U.S. Citizen or U.S. National.", "citizenship"),
    ("MUST BE A US CITIZEN", "citizenship"),
    ("U.S. citizenship is required.", "citizenship"),
    ("This role requires US citizenship.", "citizenship"),
    ("Open to U.S. citizens only.", "citizenship"),
    ("US citizens or green card holders only.", "citizenship"),
    ("Must be a United States citizen.", "citizenship"),
    ("Who May Apply: US Citizens", "citizenship"),
    # trap: a citizen *category* inside a longer label is not an eligibility line
    ("Preference Eligible United States Citizen Applying to a DCIPS Position", "none_found"),
    # export control
    ("Applicants must be a U.S. person as defined by ITAR.", "citizenship"),
    ("Candidate must qualify as a US Person under EAR.", "citizenship"),
    # clearance variants
    ("TS/SCI with polygraph required.", "clearance"),
    ("Requires TS / SCI.", "clearance"),
    ("Active Secret clearance.", "clearance"),
    ("Must hold an active secret clearance.", "clearance"),
    ("Ability to obtain a clearance.", "clearance"),
    ("Must have the ability to obtain and maintain a Secret clearance.", "clearance"),
    ("Security clearance required.", "clearance"),
    # Public Trust: parked, default not a restriction
    ("Ability to obtain a Public Trust.", "none_found"),
    # traps
    ("Must be authorized to work in the US.", "none_found"),
    (
        "We are an equal opportunity employer and consider applicants without regard to "
        "race, color, national origin, or citizenship status.",
        "none_found",
    ),
    ("Our secret sauce is great data.", "none_found"),
    ("Help us persuade stakeholders.", "none_found"),
    ("No security clearance required.", "none_found"),
    ("Customs clearance and logistics analytics.", "none_found"),
    ("U.S. citizenship preferred.", "none_found"),  # preference, not requirement -> ambiguous
]


@pytest.mark.parametrize("text,expected", RESTRICTION_CASES)
def test_restriction(text, expected):
    assert restriction(text)[0] == expected


def test_us_person_has_its_own_reason():
    value, reason = restriction("Must be a U.S. person.")
    assert value == "citizenship" and reason.startswith("us_person")


def test_public_trust_mention_is_recorded():
    value, reason = restriction("Position requires a Public Trust background check.")
    assert value == "none_found"
    assert "public trust" in reason.lower()


def test_ambiguous_and_negated_reasons():
    assert restriction("U.S. citizenship preferred.")[1].startswith("ambiguous: ")
    assert restriction("No security clearance required.")[1].startswith("negated: ")
    assert restriction("We value collaboration.") == ("none_found", None)


def test_structured_key_requirements_beat_text():
    value, reason = classify_restriction(
        "Nothing about citizenship in this text.", ["US Citizenship or National"]
    )
    assert (value, reason) == ("citizenship", "usajobs KeyRequirements")
    # structured list without a citizenship entry -> text rules still run
    assert classify_restriction("Must be a U.S. citizen.", ["Register with Selective Service"])[
        0
    ] == ("citizenship")


# --------------------------------------------------------------------- #
# OPT


@pytest.mark.parametrize(
    "text,expected",
    [
        ("OPT/CPT welcome but no H-1B sponsorship.", True),
        ("STEM OPT candidates encouraged.", True),
        ("Optional Practical Training (OPT) students may apply.", True),
        ("curricular practical training", True),
        # traps
        ("Users can opt in to marketing emails.", False),  # lowercase opt
        ("Build OPT-IN funnels.", False),
        ("Experience with CPT codes and ICD-10.", False),  # medical coding
        ("Optimize SQL queries.", False),
    ],
)
def test_opt_mentioned(text, expected):
    assert detect_opt(normalize_text(text)) is expected


# --------------------------------------------------------------------- #
# coverage + truncation


def test_text_coverage():
    assert text_coverage(None, "full text") == "full"
    assert text_coverage("snippet", None) == "truncated"
    assert text_coverage(None, None) == "empty"
    assert text_coverage("  ", "") == "empty"


def test_adzuna_snippet_cut_off_mid_sentence_is_unknown_not_sponsors():
    snippet = (
        "Join our analytics team building dashboards in Tableau and SQL. Candidates must be "
        "authorized to work in the US. We are unable to spon"
    )
    signals = classify_posting("Data Analyst", snippet, None, "FAKECO Analytics LLC")
    assert signals.text_coverage == "truncated"
    assert signals.sponsorship_stance == "none_found"  # unknown -- never "sponsors"
    assert signals.restriction == "none_found"


# --------------------------------------------------------------------- #
# cap-exempt hint


@pytest.mark.parametrize(
    "name,expected",
    [
        ("FAKE Northfield University", "likely"),
        ("FAKE Lakeside Community College", "likely"),
        ("FAKE State College", "likely"),
        ("FAKE Riverside Institute of Technology", "likely"),
        ("University of FAKE Plains", "likely"),
        # for-profit markers
        ("FAKE Career University LLC", "unknown"),
        ("FAKE College Holdings Inc.", "unknown"),
        ("FAKE University Credit Union", "unknown"),
        # parked entity types
        ("FAKE Northfield University Hospital", "unknown"),
        # no name signal
        ("FAKECO Analytics LLC", "unknown"),
        ("FAKE Research Foundation", "unknown"),
        ("Department of FAKE Affairs", "unknown"),
        (None, "unknown"),
    ],
)
def test_cap_exempt_hint(name, expected):
    assert classify_cap_exempt(name)[0] == expected


# --------------------------------------------------------------------- #
# the existing USAJobs fixture


def _fixture_items():
    data = json.loads((FIXTURES / "usajobs_sample_response.json").read_text())
    return data["SearchResult"]["SearchResultItems"]


def test_usajobs_structured_key_requirements_from_fixture():
    item = next(i for i in _fixture_items() if i["MatchedObjectId"] == "880660900")
    from src.ingestion.usajobs_parser import parse_job

    job = parse_job(item)
    key_reqs = item["MatchedObjectDescriptor"]["UserArea"]["Details"]["KeyRequirements"]
    signals = classify_posting(
        job["title"], job["description"], job["description_full"], "General Services", key_reqs
    )
    assert signals.restriction == "citizenship"
    assert signals.restriction_reason == "usajobs KeyRequirements"
    assert signals.text_coverage == "full"


def test_usajobs_text_fallback_on_fixture():
    """The 10 fixture postings whose Requirements text names citizenship are all
    caught by text when KeyRequirements is absent."""
    from src.ingestion.usajobs_parser import parse_job

    by_text = 0
    for item in _fixture_items():
        details = item["MatchedObjectDescriptor"]["UserArea"]["Details"]
        if details.get("KeyRequirements"):
            continue
        job = parse_job(item)
        signals = classify_posting(job["title"], job["description"], job["description_full"], None)
        if "citizen" in (details.get("Requirements") or "").lower():
            assert signals.restriction == "citizenship", item["MatchedObjectId"]
            by_text += 1
    assert by_text == 10
