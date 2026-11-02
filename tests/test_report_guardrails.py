"""Report guardrails (src/reports/guardrails.py): unit tests, no database."""

import numpy as np
import pandas as pd
import pytest

from src.reports.guardrails import (
    MEDIAN_RATIONALE,
    SALARY_FLOOR,
    SKILL_FLOOR,
    TRUNCATION_LABEL,
    Count,
    FlooredSalary,
    Gap,
    GuardrailError,
    Rate,
    Ratio,
    SalaryDiff,
    SalarySummary,
    Stat,
    apply_floor,
    below_floor,
    check_salary_wording,
    round_half_up,
    skill_rate,
    summarize_salary,
)
from src.reports.markdown import render_cell

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


def test_a_small_rate_never_reads_as_zero_or_whole():
    assert Rate(1, 2835, unit="postings").render() == "<0.1% (1 of 2,835 postings)"
    assert Rate(2834, 2835, unit="postings").render() == ">99.9% (2,834 of 2,835 postings)"
    assert Rate(1, 2835, pct=0.0).render() == "<0.1% (1 of 2,835)"  # the view's own 0.0 too
    # exact zeros and hundreds, and rates that don't round to them, are unchanged
    assert Rate(0, 2835).render() == "0.0% (0 of 2,835)"
    assert Rate(2835, 2835).render() == "100.0% (2,835 of 2,835)"
    assert Rate(1, 1000).render() == "0.1% (1 of 1,000)"
    assert Rate(999, 1000).render() == "99.9% (999 of 1,000)"
    # only the display changes: the value is still the rounded number
    assert Rate(1, 2835).value == 0.0 and Rate(2834, 2835).value == 100.0


def test_a_zero_denominator_renders_as_not_applicable():
    assert Rate(0, 0, unit="jobs").render() == "n/a (0 of 0 jobs)"


def test_counts_ratios_and_stats_render_with_their_n():
    assert Count(1483).render() == "1,483"
    assert (
        Ratio(1353, 609, num_unit="tags", den_unit="jobs").render()
        == "2.22 (1,353 tags / 609 jobs)"
    )
    assert Ratio(7, 2, places=1, suffix="x").render() == "3.5x (7 / 2)"
    assert Stat(5739.0, 5, fmt="{:,.0f} chars").render() == "5,739 chars (n=5)"
    assert Stat(235.0, 609, iqr=(224.0, 244.0)).render() == "235 (IQR 224–244; n=609)"
    assert Ratio(1353.0, 609).render() == "2.22 (1,353 / 609)"
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


# --------------------------------------------------------------------- #
# salary floor, SalaryDiff, wording


def summary(basis="employer-disclosed", n=20, median=100_000.0, group=""):
    if median is None:
        return SalarySummary(basis, n, None, None, None, group)
    return SalarySummary(basis, n, median, median - 10_000, median + 10_000, group)


def test_the_salary_floor_withholds_the_median_but_shows_n():
    assert SALARY_FLOOR == 15
    assert FlooredSalary(summary(n=15)).render() == summary(n=15).render()
    withheld = FlooredSalary(summary(n=14))
    assert withheld.withheld and "$" not in withheld.render()
    assert withheld.render() == "withheld: n=14 is under the n ≥ 15 floor (employer-disclosed)"
    assert FlooredSalary(summary(n=0, median=None)).render() == (
        "no data (n=0, employer-disclosed)"
    )
    with pytest.raises(GuardrailError):
        FlooredSalary(100_000)


def test_a_salary_diff_shows_both_medians_and_both_n():
    diff = SalaryDiff(summary("Adzuna-predicted", 40, 106_000.0), summary(n=30))
    assert diff.dollars == 6_000
    assert diff.render() == (
        "+$6,000 (Adzuna-predicted $106,000, n=40 vs employer-disclosed $100,000, n=30)"
    )
    groups = SalaryDiff(summary(group="senior", median=120_000.0), summary(group="no title signal"))
    assert groups.render().startswith("+$20,000 (senior (employer-disclosed) $120,000, n=20 vs ")
    lower = SalaryDiff(summary(median=90_000.0, group="mid"), summary(group="senior"))
    assert lower.render().startswith("-$10,000 ")


@pytest.mark.parametrize(
    "a,b,match",
    [
        (summary(), summary(), "two different bases"),
        (summary(group="senior"), summary(group="senior"), "two different bases"),
        (summary("Adzuna-predicted", n=14), summary(), "under the n ≥ 15 floor"),
        (summary("Adzuna-predicted"), summary(n=0, median=None), "no data"),
        (100_000, summary(), "two SalarySummary"),
    ],
)
def test_salary_diff_refusals(a, b, match):
    with pytest.raises(GuardrailError, match=match):
        SalaryDiff(a, b)


def test_salary_wording_allows_mean_only_in_the_median_rationale():
    check_salary_wording(f"Median $100,000. {MEDIAN_RATIONALE} What it means: ...")
    for bad in ("The mean is $1", "an AVERAGE of", "avg salary", "Mean salary"):
        with pytest.raises(GuardrailError, match="median and IQR only"):
            check_salary_wording(f"{MEDIAN_RATIONALE} {bad}")
    with pytest.raises(GuardrailError):  # the rationale is allowed once, not twice
        check_salary_wording(MEDIAN_RATIONALE + " " + MEDIAN_RATIONALE)


def test_salary_summaries_can_carry_a_group():
    frame = salaries()
    s = summarize_salary(frame, "employer-disclosed", "v_commercial_salary_clean", group="senior")
    assert s.group == "senior" and s.label == "senior (employer-disclosed)"
    assert s.render() == "$100,000 (IQR $90,000–$110,000; n=5, employer-disclosed)"  # unchanged


def test_floored_salaries_and_diffs_render_in_tables():
    assert render_cell(FlooredSalary(summary(n=3))).startswith("withheld")
    assert render_cell(SalaryDiff(summary("Adzuna-predicted"), summary())).startswith("+$0")
