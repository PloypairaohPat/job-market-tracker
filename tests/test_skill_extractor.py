"""Tests for the skill taxonomy and extractor.

The precision cases here are the contract: every ambiguous term in the
taxonomy earns its place by passing a false-positive test. When adding
a skill, add its trap case here first.
"""

import pytest

from src.cleaning.skill_extractor import (
    VALID_CATEGORIES,
    SkillExtractor,
    load_taxonomy,
)


@pytest.fixture(scope="module")
def taxonomy():
    return load_taxonomy()


@pytest.fixture(scope="module")
def extractor(taxonomy):
    return SkillExtractor(taxonomy)


# ------------------------------------------------------------------ #
# taxonomy integrity


def test_taxonomy_loads_and_compiles(taxonomy):
    assert len(taxonomy) >= 50  # the guide's "top 50 skills" floor


def test_taxonomy_names_unique(taxonomy):
    names = [s.name for s in taxonomy]
    assert len(names) == len(set(names))


def test_taxonomy_categories_valid(taxonomy):
    assert {s.category for s in taxonomy} <= VALID_CATEGORIES


def test_taxonomy_confidences_in_range(taxonomy):
    assert all(0.0 < s.confidence <= 1.0 for s in taxonomy)


# ------------------------------------------------------------------ #
# straightforward matches


def test_core_skills_extracted(extractor):
    text = "Strong SQL skills required. Experience with Python and Tableau preferred."
    found = extractor.extract(text)
    assert {"SQL", "Python", "Tableau"} <= set(found)


def test_alias_resolves_to_canonical(extractor):
    found = extractor.extract("Experience with Postgres and PowerBI required.")
    assert "PostgreSQL" in found and "Postgres" not in found
    assert "Power BI" in found and "PowerBI" not in found


def test_multiword_and_symbol_terms(extractor):
    found = extractor.extract("You will design A/B tests and use scikit-learn and Power BI.")
    assert {"A/B Testing", "scikit-learn", "Power BI"} <= set(found)


def test_empty_and_none_text(extractor):
    assert extractor.extract("") == {}
    assert extractor.extract(None) == {}


# ------------------------------------------------------------------ #
# precision traps — each ambiguous taxonomy term must pass its trap


def test_excel_not_matched_in_verb_usage(extractor):
    assert "Excel" not in extractor.extract("You will excel in a fast-paced environment.")
    assert "Excel" in extractor.extract("Advanced Excel and PowerPoint skills.")


def test_r_language_context_anchoring(extractor):
    assert "R" in extractor.extract("Statistical analysis in R or Python.")
    assert "R" in extractor.extract("Proficiency with Python/R for modeling.")
    assert "R" in extractor.extract("R programming experience required.")
    assert "R" not in extractor.extract("Partner with HR and R&D teams.")
    assert "R" not in extractor.extract("401(k) match. EEO employer M/F/D/V. Section R.")


def test_sas_case_sensitivity(extractor):
    assert "SAS" in extractor.extract("Experience with SAS or SPSS.")
    assert "SAS" not in extractor.extract("Trabajarás con otras cosas sas.")  # lowercase


def test_spark_not_matched_as_verb(extractor):
    assert "Spark" in extractor.extract("Big data processing with Spark and Kafka.")
    assert "Spark" in extractor.extract("PySpark experience is a plus.")
    assert "Spark" not in extractor.extract("A chance to spark change and sparked innovation.")


def test_dbt_lowercase_brand(extractor):
    assert "dbt" in extractor.extract("Transform data with dbt and Snowflake.")
    assert "dbt" not in extractor.extract("DBT therapy experience.")  # uppercase = not the tool


def test_git_not_matched_inside_words(extractor):
    assert "Git" in extractor.extract("Version control with Git.")
    assert "Git" in extractor.extract("Share your GitHub profile.")
    assert "Git" not in extractor.extract("Legitimate digital initiatives.")


def test_looker_boundary(extractor):
    assert "Looker" in extractor.extract("Build dashboards in Looker.")
    assert "Looker" not in extractor.extract("Not for onlookers.")


def test_java_not_matched_in_javascript(extractor):
    found = extractor.extract("Frontend work in JavaScript only.")
    assert "Java" not in found


def test_mode_requires_full_brand(extractor):
    assert "Mode" not in extractor.extract("Work in hybrid mode from our NYC office.")
    assert "Mode" in extractor.extract("Build reports in Mode Analytics.")


# ------------------------------------------------------------------ #
# federal-vocabulary additions (Phase 3 #2: commercial vs federal skill demand)


def test_sql_structured_query_language_alias(extractor):
    found = extractor.extract("Experience with structured query language required.")
    assert "SQL" in found


def test_spss_case_sensitivity(extractor):
    assert "SPSS" in extractor.extract("Experience with SPSS or SAS required.")
    assert "SPSS" not in extractor.extract("Statistical work using spss-like tools.")  # lowercase


def test_gis_context_anchoring(extractor):
    assert "GIS" in extractor.extract("Proficiency with ArcGIS required.")
    assert "GIS" in extractor.extract("Experience with GIS software for spatial analysis.")
    assert "GIS" in extractor.extract("Using GIS to visualize geographic data.")
    assert "GIS" not in extractor.extract(
        "Coordinate with the Global Information Security (GIS) team on access requests."
    )


def test_ssis_case_sensitivity(extractor):
    assert "SSIS" in extractor.extract("Build ETL packages with SSIS.")
    assert "SSIS" not in extractor.extract("Random text with ssis lowercase noise.")


def test_ssrs_case_sensitivity(extractor):
    assert "SSRS" in extractor.extract("Author reports in SSRS.")
    assert "SSRS" not in extractor.extract("Random text with ssrs lowercase noise.")
