"""Report guardrails (src/reports/guardrails.py): unit tests, no database."""

import numpy as np
import pandas as pd
import pytest

from src.reports.guardrails import (
    SKILL_FLOOR,
    TRUNCATION_LABEL,
    Count,
    Gap,
    GuardrailError,
    Rate,
    Ratio,
    SalarySummary,
    Stat,
    apply_floor,
    below_floor,
    round_half_up,
    skill_rate,
    summarize_salary,
)

# --------------------------------------------------------------------- #
# rates always carry their denominator


def test_a_rate_renders_with_its_numerator_and_denominator():
    assert Rate(180, 533, unit="tags").render() == "33.8% (180 of 533 tags)"
    assert Rate(np.int64(5), np.int64(10)).render() == "50.0% (5 of 10)"


@pytest.mark.parametrize("denominator", [None, float("nan"), 2.5, -1])
def test_a_rate_without_a_usable_denominator_is_refused(denominator):
    with pytest.raises(GuardrailError):
        Rate(1, denominator)


def test_a_rate_whose_numerator_exceeds_its_denominator_is_refused():
    with pytest.raises(GuardrailError, match="exceeds"):
        Rate(6, 5)


def test_the_views_percentage_must_match_the_declared_denominator():
    # 180 tags of 533 is 33.8%; quoting it against 1,483 jobs is the classic mistake
    assert Rate(180, 533, pct=33.8).render() == "33.8% (180 of 533)"
    with pytest.raises(GuardrailError, match="wrong denominator"):
        Rate(180, 1483, pct=33.8)


def test_rounding_matches_postgres_round_half_up():
    assert round_half_up(0.25) == 0.3  # Python's round() gives 0.2
    assert Rate(1, 400).render() == "0.3% (1 of 400)"
    assert Rate(1, 400, pct=0.3).value == 0.3


def test_a_zero_denominator_renders_as_not_applicable():
    assert Rate(0, 0, unit="jobs").render() == "n/a (0 of 0 jobs)"


def test_counts_ratios_and_stats_render_with_their_n():
    assert Count(1483).render() == "1,483"
    assert Ratio(1353, 609, terms="tags / jobs").render() == "2.22 (1,353 / 609 tags / jobs)"
    assert Ratio(7, 2, places=1, suffix="x").render() == "3.5x (7 / 2)"
    assert Stat(5739.0, 5, fmt="{:,.0f} chars").render() == "5,739 chars (n=5)"
    assert Stat(None, 0).render() == "n/a (n=0)"
    with pytest.raises(GuardrailError):
        Stat(float("nan"), 5)
    with pytest.raises(GuardrailError):
        Count(-1)


def test_a_gap_is_only_between_two_rates_and_shows_both():
    gap = Gap(Rate(180, 533, unit="tags"), Rate(26, 236, unit="tags"))
    assert gap.render() == "+22.8 pp (33.8% (180 of 533 tags) vs 11.0% (26 of 236 tags))"
    with pytest.raises(GuardrailError):
        Gap(33.8, Rate(26, 236))


# --------------------------------------------------------------------- #
# reporting floors


def test_the_floors_are_the_investigation_2_thresholds():
    assert SKILL_FLOOR == {"commercial": 15, "federal": 5}
    assert not below_floor(15, "commercial") and below_floor(14, "commercial")
    assert not below_floor(5, "federal") and below_floor(4, "federal")


def test_apply_floor_splits_kept_and_suppressed_rows():
    frame = pd.DataFrame({"name": ["SQL", "SPSS", "GIS"], "n": [7, 5, 4]})
    kept, suppressed = apply_floor(frame, "federal", "n")
    assert kept["name"].tolist() == ["SQL", "SPSS"]
    assert suppressed["name"].tolist() == ["GIS"]
    kept, suppressed = apply_floor(frame, "commercial", "n")
    assert kept.empty and len(suppressed) == 3


def test_floors_refuse_unknown_markets_and_missing_columns():
    frame = pd.DataFrame({"n": [1]})
    with pytest.raises(GuardrailError):
        apply_floor(frame, "pooled", "n")
    with pytest.raises(GuardrailError):
        apply_floor(frame, "federal", "n_jobs")


# --------------------------------------------------------------------- #
# commercial skill rates are truncation-floored


def test_commercial_skill_rates_are_marked_truncation_floored():
    assert skill_rate(72, 1483, "commercial").truncation_floored
    assert not skill_rate(27, 70, "federal").truncation_floored
    assert TRUNCATION_LABEL == "truncation-floored"
    with pytest.raises(GuardrailError):
        skill_rate(1, 2, "both")


# --------------------------------------------------------------------- #
# salary: clean population, median + IQR, never pooled


def salaries(**overrides):
    frame = pd.DataFrame(
        {
            # right-skewed disclosed salaries: the mean is far above the median
            "salary_midpoint": [80_000, 90_000, 100_000, 110_000, 400_000, 120_000, 130_000],
            "salary_is_predicted": [False, False, False, False, False, True, True],
        }
    )
    return frame.assign(**overrides)


def test_salary_is_median_and_iqr_never_the_mean():
    summary = summarize_salary(salaries(), "employer-disclosed", "v_commercial_salary_clean")
    assert (summary.n, summary.median, summary.p25, summary.p75) == (5, 100_000, 90_000, 110_000)
    assert not hasattr(summary, "mean")
    assert summary.render() == "$100,000 (IQR $90,000–$110,000; n=5, employer-disclosed)"


def test_disclosed_and_predicted_are_summarized_separately():
    predicted = summarize_salary(salaries(), "Adzuna-predicted", "v_commercial_salary_clean")
    assert (predicted.n, predicted.median) == (2, 125_000)
    with pytest.raises(GuardrailError, match="never pooled"):
        summarize_salary(salaries(), "all", "v_commercial_salary_clean")


def test_salary_without_the_predicted_flag_is_refused():
    frame = salaries().drop(columns="salary_is_predicted")
    with pytest.raises(GuardrailError, match="pool"):
        summarize_salary(frame, "employer-disclosed", "v_commercial_salary_clean")
    with pytest.raises(GuardrailError, match="NULL"):
        summarize_salary(
            salaries(salary_is_predicted=[False] * 6 + [None]),
            "employer-disclosed",
            "v_commercial_salary_clean",
        )


def test_salary_from_outside_the_clean_population_is_refused():
    # an unknown view without the filter columns: can't prove it's ok/USD/year
    with pytest.raises(GuardrailError, match="clean-salary view"):
        summarize_salary(salaries(), "employer-disclosed", "v_market_jobs")
    # filter columns present: every row must be ok / USD / year
    clean = salaries(salary_quality="ok", salary_currency="USD", salary_period="year")
    assert summarize_salary(clean, "employer-disclosed", "anything").n == 5
    for column, bad in [
        ("salary_quality", "suspect"),
        ("salary_currency", "GBP"),
        ("salary_period", "hour"),
    ]:
        frame = clean.copy()
        frame.loc[0, column] = bad
        with pytest.raises(GuardrailError, match=column):
            summarize_salary(frame, "employer-disclosed", "anything")


def test_an_empty_basis_renders_as_not_applicable():
    frame = salaries(salary_is_predicted=[False] * 7)
    summary = summarize_salary(frame, "Adzuna-predicted", "v_commercial_salary_clean")
    assert summary == SalarySummary("Adzuna-predicted", 0, None, None, None)
    assert summary.render() == "n/a (n=0, Adzuna-predicted)"
