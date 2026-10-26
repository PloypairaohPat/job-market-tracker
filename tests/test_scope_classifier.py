"""Unit tests for src/cleaning/scope_classifier.py — pure functions, no I/O.

Trap tests first, per project convention (skill_extractor.py): every
non-obvious classification boundary gets a test that would fail if the
logic silently regressed.
"""

import pytest

from src.cleaning.scope_classifier import classify_scope
from src.cleaning.skill_extractor import SkillExtractor


@pytest.fixture(scope="module")
def extractor() -> SkillExtractor:
    return SkillExtractor()


def test_non_usajobs_source_always_in_scope(extractor):
    """Commercial keyword search (Adzuna) is far less polluted -- default
    to including it, regardless of category or text."""
    in_scope, reason = classify_scope("adzuna", None, "", extractor)
    assert in_scope is True
    assert reason == "non_usajobs_default"


def test_usajobs_no_category_is_out_of_scope(extractor):
    """No category = no signal to include on -- flag out, don't guess in."""
    assert classify_scope("usajobs", None, "some text", extractor) == (False, "no_category")
    assert classify_scope("usajobs", "", "some text", extractor) == (False, "no_category")


def test_clean_in_scope_categories_pass_without_needing_skill_signal(extractor):
    """Data Science / Operations Research / Statistics are unambiguous --
    should pass even with zero skill mentions in the text."""
    for category in ("Data Science Series", "Operations Research", "Statistics"):
        in_scope, reason = classify_scope("usajobs", category, "", extractor)
        assert in_scope is True
        assert reason == f"series:{category}"


def test_clearly_irrelevant_category_is_excluded(extractor):
    in_scope, reason = classify_scope("usajobs", "Budget Analysis", "SQL Python Tableau", extractor)
    assert in_scope is False
    assert reason == "category_excluded:Budget Analysis"


def test_ambiguous_category_passes_at_skill_density_threshold(extractor):
    """Empirically validated (docs/data_dictionary.md): >=2 distinct
    analytics-category skills -> in scope."""
    text = "Program Analyst (Informatics). Requires SQL and Python experience."
    in_scope, reason = classify_scope("usajobs", "Management And Program Analysis", text, extractor)
    assert in_scope is True
    assert reason == "skill_density:Management And Program Analysis:2"


def test_ambiguous_category_fails_below_skill_density_threshold(extractor):
    text = "Management Analyst. Responsible for forecasting and budget oversight."
    in_scope, reason = classify_scope("usajobs", "Management And Program Analysis", text, extractor)
    assert in_scope is False
    assert reason.startswith("skill_density:Management And Program Analysis:")
    # 'Forecasting' alone is a single, weak signal -- below the threshold
    assert reason.endswith(":1") or reason.endswith(":0")


def test_ambiguous_category_zero_skills_is_out_of_scope(extractor):
    in_scope, reason = classify_scope(
        "usajobs", "Information Technology Management", "manages IT infrastructure", extractor
    )
    assert in_scope is False
    assert reason == "skill_density:Information Technology Management:0"


def test_multi_category_uses_any_matching_label_not_just_first():
    """Real case: job 865002200, 'INTERDISCIPLINARY GENERAL ENGINEER/
    OPERATIONS RESEARCH ANALYST', is tagged both General Engineering
    (excluded) and Operations Research (clean in-scope). The posting
    must be included -- the excluded label must not short-circuit it."""
    extractor = SkillExtractor()
    category = "General Engineering; Operations Research"
    in_scope, reason = classify_scope("usajobs", category, "", extractor)
    assert in_scope is True
    assert reason == "series:Operations Research"


def test_multi_category_ambiguous_label_still_gets_tie_broken(extractor):
    """One excluded label + one ambiguous label -> the ambiguous one
    still goes through the skill-density tie-break, not straight to
    category_excluded."""
    category = "Budget Analysis; Management And Program Analysis"
    text = "Data Analyst role requiring SQL, Python, and Tableau."
    in_scope, reason = classify_scope("usajobs", category, text, extractor)
    assert in_scope is True
    assert reason.startswith("skill_density:Management And Program Analysis:")


def test_only_analytics_category_skills_count_toward_density(extractor):
    """A 'soft' skill (not in the analytics categories) shouldn't count
    toward the threshold -- the tie-break should reflect genuine
    technical signal, not any taxonomy hit. 'Stakeholder Management' is
    a real taxonomy entry with category='soft'; paired with one real
    'language' hit (SQL), the density should be 1, not 2."""
    text = "Program Analyst with strong stakeholder management skills and SQL experience."
    in_scope, reason = classify_scope("usajobs", "Management And Program Analysis", text, extractor)
    assert in_scope is False
    assert reason == "skill_density:Management And Program Analysis:1"
