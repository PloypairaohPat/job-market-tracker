"""Guardrails for reports that touch DOL LCA (H-1B) filings: report 3.

src/visa/README.md's "What this can't tell you", as code:

  - An LCA is a FILING, not an approval or a hire. `FilingCount` refuses a
    label that calls filings hires or approvals, or that doesn't say it
    counts filings. `FilingWage` always renders as the offered wage on LCA
    filings, never as what postings pay.
  - Counts favour large filers, staffing firms included.
  - "unknown" is never "no", and an employer with no LCA match is "no match
    found", never a refusal to sponsor. `check_sponsorship_text` refuses
    rendered text that states such a negative.
  - Adzuna text is truncated, so a missing sponsorship sentence proves nothing.
  - Cap-exempt is only a hint.
  - Aggregate and employer-level only: `check_aggregate` refuses any view
    frame carrying per-job or per-filing columns (titles, URLs, case
    numbers), so the private Visa outlook dashboard can't be recreated.

LCA_CAVEATS holds the Methods wording for each; a report that uses LCA data
must print every REQUIRED_CAVEATS entry (`check_caveats`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.reports.guardrails import GuardrailError, _count

LCA_CAVEATS = {
    "filing_not_hire": (
        "**An LCA is a filing, not an approval or a hire.** It is the Department of Labor step "
        "before an H-1B petition. Employers file more LCAs than they use, and one LCA can cover "
        "several positions or none. A count shows willingness to file for a kind of role, not how "
        "many people got visas."
    ),
    "large_filers": (
        "**Counts favour large filers, staffing firms included.** Big employers and IT staffing or "
        "outsourcing firms file thousands, so a high count says little about one role, and pooled "
        "filing figures (such as a pooled offered wage) are dominated by the biggest filers."
    ),
    "unknown_not_no": (
        '**"Unknown" is never "no".** An employer with no LCA match is "no match found": the '
        "name may differ between the posting and DOL's file, or the employer may file under "
        'another entity. Only a posting\'s own words put it in "closed".'
    ),
    "truncated_text": (
        "**Adzuna text is truncated** at about 500 characters, so a sponsorship sentence is often "
        "cut off: a missing sentence proves nothing either way."
    ),
    "cap_exempt_hint": (
        "**Cap-exempt is only a hint,** from the employer's name. The LCA data has no cap-exempt "
        "field; for-profit colleges aren't exempt, and many exempt nonprofits and labs don't say "
        "so in their name."
    ),
    "e_verify": (
        "**E-Verify isn't covered.** The STEM OPT extension needs an E-Verify employer; nothing "
        "here checks that."
    ),
    "rules_change": (
        "**Rules change,** and this describes data; it isn't immigration advice. Check plans with "
        "a DSO (and an immigration attorney for anything consequential)."
    ),
}
REQUIRED_CAVEATS = (
    "filing_not_hire",
    "large_filers",
    "unknown_not_no",
    "truncated_text",
    "cap_exempt_hint",
)
README_POINTER = "src/visa/README.md"

UNMATCHED_LABEL = "no match found"
BUCKETS = ("closed", "strong", "possible", "unknown")
BUCKET_LABELS = {
    "closed": "closed (the posting says no)",
    "strong": 'strong (not a "yes")',
    "possible": "possible",
    "unknown": 'unknown (no signal; never a "no")',
}
# columns that would make a frame per-job or per-filing rather than aggregate
ROW_LEVEL_COLUMNS = frozenset(
    {"job_id", "title", "redirect_url", "description", "description_full", "case_number"}
)

_FILING_WORD = re.compile(r"\b(LCAs?|filings?)\b", re.IGNORECASE)
_HIRE_OR_APPROVAL = re.compile(
    r"\b(hires?|hired|hiring|approv\w*|granted|issued|visas)\b", re.IGNORECASE
)
_NEGATIVE_CLAIMS = re.compile(
    r"\b(?:does\s+not|doesn't|do\s+not|don't|never|won't|will\s+never)\s+(?:sponsor|file)\w*"
    r"|\bnon-?sponsor\w*"
    r"|\bno\s+sponsorship\s+history\b"
    r"|\b(?:H-1B|LCA)s?\s+(?:hires|approvals)\b",
    re.IGNORECASE,
)


def check_filing_label(label: str) -> str:
    if not _FILING_WORD.search(label):
        raise GuardrailError(f"label {label!r} must say it counts LCA filings")
    found = _HIRE_OR_APPROVAL.search(label)
    if found:
        raise GuardrailError(
            f"label {label!r} calls LCA filings {found.group(0)!r}: an LCA is a filing, "
            "not an approval or a hire"
        )
    return label


@dataclass(frozen=True)
class FilingCount:
    """A count of LCA filings, labelled as filings and never as hires or approvals."""

    n: int
    label: str = "LCA filings"

    def __post_init__(self) -> None:
        object.__setattr__(self, "n", _count(self.n, "filing count"))
        check_filing_label(self.label)

    def render(self) -> str:
        return f"{self.n:,} {self.label}"


@dataclass(frozen=True)
class FilingWage:
    """Median and IQR of the offered annual wage on LCA filings, with the filing
    and employer counts behind it. It describes filings, not what postings pay."""

    n_filings: int
    n_employers: int
    median: float | None = None
    p25: float | None = None
    p75: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "n_filings", _count(self.n_filings, "filings behind a wage"))
        object.__setattr__(self, "n_employers", _count(self.n_employers, "employers behind a wage"))
        if self.n_filings and None in (self.median, self.p25, self.p75):
            raise GuardrailError("a wage over filings needs its median and IQR")

    def render(self) -> str:
        if self.n_filings == 0:
            return "n/a (0 LCA filings with a convertible wage)"
        return (
            f"${self.median:,.0f} (IQR ${self.p25:,.0f}–${self.p75:,.0f}; "
            f"n={self.n_filings:,} LCA filings from {self.n_employers:,} employer(s))"
        )


def check_sponsorship_text(text: str) -> None:
    """Refuse rendered text that claims an employer won't or doesn't sponsor, or
    that counts filings as hires or approvals."""
    found = sorted({m.group(0) for m in _NEGATIVE_CLAIMS.finditer(text)})
    if found:
        raise GuardrailError(
            f"report states what the data can't support: {found}. Unmatched is "
            f"{UNMATCHED_LABEL!r} and unknown is never 'no'; LCAs are filings."
        )


def check_caveats(text: str) -> None:
    missing = [key for key in REQUIRED_CAVEATS if LCA_CAVEATS[key] not in text]
    if missing:
        raise GuardrailError(f"report uses LCA data but omits the caveats {missing}")


def check_aggregate(frames: dict) -> None:
    """Report 3 is aggregate and employer-level only."""
    for view, frame in frames.items():
        row_level = sorted(ROW_LEVEL_COLUMNS & set(frame.columns))
        if row_level:
            raise GuardrailError(
                f"{view} carries per-job or per-filing columns {row_level}: this report is "
                "aggregate and employer-level only"
            )
