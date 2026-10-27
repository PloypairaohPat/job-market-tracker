"""LCA guardrails (src/reports/lca_guardrails.py): unit tests, no database."""

import pandas as pd
import pytest

from src.reports.guardrails import GuardrailError
from src.reports.lca_guardrails import (
    BUCKET_LABELS,
    BUCKETS,
    LCA_CAVEATS,
    REQUIRED_CAVEATS,
    UNMATCHED_LABEL,
    FilingCount,
    FilingWage,
    check_aggregate,
    check_caveats,
    check_filing_label,
    check_sponsorship_text,
)
from src.reports.markdown import render_cell


def test_a_filing_count_says_it_counts_filings():
    assert FilingCount(26).render() == "26 LCA filings"
    label = "certified analytics-SOC H-1B LCA filings"
    assert FilingCount(1_200, label).render() == f"1,200 {label}"
    assert render_cell(FilingCount(3)) == "3 LCA filings"
    with pytest.raises(GuardrailError, match="must say it counts LCA filings"):
        FilingCount(5, "certified H-1B cases")


@pytest.mark.parametrize(
    "label",
    [
        "H-1B hires",
        "LCA filings (hired)",
        "approved LCA filings",
        "LCA approvals",
        "filings granted",
        "LCA filings = visas issued",
        "hiring LCA filings",
    ],
)
def test_filings_are_never_labelled_hires_or_approvals(label):
    with pytest.raises(GuardrailError):
        check_filing_label(label)


def test_a_filing_wage_is_median_iqr_and_its_filings():
    wage = FilingWage(n_filings=9, n_employers=1, median=73_000, p25=70_000, p75=80_000)
    assert wage.render() == "$73,000 (IQR $70,000–$80,000; n=9 LCA filings from 1 employer(s))"
    assert "pay" not in wage.render() and not hasattr(wage, "mean")
    assert FilingWage(0, 0).render() == "n/a (0 LCA filings with a convertible wage)"
    with pytest.raises(GuardrailError):
        FilingWage(n_filings=3, n_employers=1, median=70_000)  # no IQR


@pytest.mark.parametrize(
    "text",
    [
        "FAKECO doesn't sponsor",
        "these employers do not sponsor H-1B",
        "Acme never files LCAs",
        "a non-sponsoring employer",
        "employers with no sponsorship history",
        "30 H-1B hires",
        "12 LCA approvals",
    ],
)
def test_negative_claims_the_data_cant_support_are_refused(text):
    with pytest.raises(GuardrailError, match="can't support"):
        check_sponsorship_text(f"Some report text. {text}.")


def test_the_wording_the_report_uses_passes():
    check_sponsorship_text(
        " ".join(LCA_CAVEATS.values())
        + f" {UNMATCHED_LABEL}. posting: will not sponsor. "
        + " ".join(BUCKET_LABELS.values())
    )


def test_every_required_caveat_must_appear():
    assert set(REQUIRED_CAVEATS) == {
        "filing_not_hire",
        "large_filers",
        "unknown_not_no",
        "truncated_text",
        "cap_exempt_hint",
    }
    full = "\n".join(LCA_CAVEATS.values())
    check_caveats(full)
    with pytest.raises(GuardrailError, match="unknown_not_no"):
        check_caveats(full.replace(LCA_CAVEATS["unknown_not_no"], ""))


def test_buckets_are_labelled_so_unknown_is_never_no():
    assert BUCKETS == ("closed", "strong", "possible", "unknown")
    assert 'never a "no"' in BUCKET_LABELS["unknown"]
    assert 'not a "yes"' in BUCKET_LABELS["strong"]


def test_frames_with_per_job_or_per_filing_columns_are_refused():
    check_aggregate(
        {"v_employer_postings": pd.DataFrame(columns=["market", "employer_key", "n_postings"])}
    )
    for column in ("job_id", "title", "redirect_url", "case_number"):
        with pytest.raises(GuardrailError, match="aggregate and employer-level only"):
            check_aggregate({"v_x": pd.DataFrame(columns=["market", column])})
