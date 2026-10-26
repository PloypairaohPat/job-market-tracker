"""Posting-text visa signals -- pure functions, no I/O.

What a posting itself says about someone on F-1 OPT who will later need
H-1B sponsorship. Four independent outputs (see docs/data_dictionary.md,
`job_visa_signals`):

- restriction         citizenship | clearance | none_found
- sponsorship_stance  will_not_sponsor | will_sponsor | none_found
- opt_mentioned       OPT / CPT / practical training named anywhere
- cap_exempt_hint     likely | unknown   (from the company NAME only)

plus `text_coverage` (full | truncated | empty), which says how much of
the posting the classifier could read. **none_found on truncated text
means "unknown", never "sponsors"** -- Adzuna caps descriptions at ~500
characters, so the sentence that matters is often cut off.

Rules follow src/cleaning/README.md: flag, don't guess; precision over
recall, with a trap test (tests/test_posting_signals.py) before each
rule. Judgment calls:

- "Authorized to work in the US" alone is NOT a restriction and NOT
  will_not_sponsor: OPT is work authorization. It only becomes
  will_not_sponsor next to "without sponsorship", "now or in the
  future" and similar.
- "U.S. person" (export-control / ITAR wording) is a citizenship
  restriction with its own reason: it excludes F-1 holders.
- Security clearances (TS/SCI, active Secret, "ability to obtain a
  clearance") are a restriction: a clearance requires citizenship.
- "Public Trust" is NOT a restriction (parked for the owner); the
  mention is recorded as the reason so it stays visible.
- A trigger word that no rule can read cleanly (e.g. "U.S. citizenship
  preferred", "Will you now or in the future require sponsorship?")
  is none_found with reason "ambiguous: <phrase>". A negated clearance
  ("no security clearance required") is none_found, reason "negated: ...".
- Conflicting sponsorship statements (a will-not AND a will) are
  none_found, reason "ambiguous: conflicting ...".
- USAJobs: a "US Citizenship" entry in the structured
  UserArea.Details.KeyRequirements beats text. When that field is
  absent, or lists no citizenship entry, the text rules still run (the
  field is filled in for only 1 of 25 fixture postings).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NONE_FOUND = "none_found"

# --------------------------------------------------------------------- #
# text normalization


_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', " ": " "})
_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Straight quotes, NBSP -> space, collapsed whitespace. Case is kept:
    a few rules (US, OPT, CPT) are deliberately case-sensitive."""
    return _WS.sub(" ", text.translate(_QUOTES)).strip()


# "U.S." / "U.S.A." / "US" (uppercase only -- lowercase "us" is a pronoun) /
# "United States" / "American"
_US = r"(?:U\.\s?S\.(?:\s?A\.)?|(?-i:USA?)|United\s+States|American)"
_H1B = r"H[\s-]?1[\s-]?B"
_VISA_WORD = rf"(?:visa|{_H1B}|immigration|employment|work|employer)"
_NEG_BEFORE = re.compile(
    r"\b(?:no|not|never|without|unable|cannot|can't|won't|don't|doesn't|isn't|aren't)\b[^.;:!?]{0,25}$",
    re.IGNORECASE,
)


def _rx(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern:
    return re.compile(pattern, flags)


def _negated(text: str, start: int) -> bool:
    return bool(_NEG_BEFORE.search(text[max(0, start - 30) : start]))


def _snippet(text: str, m: re.Match, pad: int = 30) -> str:
    s = text[max(0, m.start() - pad) : m.end() + pad].strip()
    return s


# --------------------------------------------------------------------- #
# restriction rules: (label, pattern)

_CITIZENSHIP_RULES: list[tuple[str, re.Pattern]] = [
    (
        "citizenship",
        _rx(rf"\bmust\s+(?:be|hold|have|possess)\s+(?:an?\s+)?{_US}\s+citizen(?:ship)?\b"),
    ),
    ("citizenship", _rx(rf"\b{_US}\s+citizenship\s+(?:is\s+)?(?:required|mandatory)\b")),
    (
        "citizenship",
        _rx(
            rf"\brequires?\s+(?:applicants?\s+to\s+(?:be|have)\s+)?(?:an?\s+)?{_US}\s+citizen(?:ship|s)?\b"
        ),
    ),
    (
        "citizenship",
        _rx(
            rf"\b(?:only\s+(?:open\s+to\s+)?{_US}\s+citizens|{_US}\s+citizens\s+only"
            rf"|open\s+(?:only\s+)?to\s+{_US}\s+citizens)\b"
        ),
    ),
    (
        "citizenship",
        _rx(
            rf"\b{_US}\s+citizens?\s+(?:or|and|/)\s+(?:lawful\s+)?"
            r"(?:permanent\s+residents?|green\s+card\s+holders?)\s+only\b"
        ),
    ),
    # USAJobs boilerplate eligibility line.
    ("citizenship", _rx(rf"\bwho\s+may\s+apply\s*:?\s*(?:only\s+)?{_US}\s+citizens\b")),
    # Export-control wording. Dotted "U.S." any case, or uppercase "US".
    ("us_person (export control; excludes F-1)", _rx(r"\b(?:U\.S\.|(?-i:US))\s+persons?\b")),
]

_CLEARANCE_RULES: list[tuple[str, re.Pattern]] = [
    ("clearance", _rx(r"\bTS\s*/\s*SCI\b")),
    (
        "clearance",
        _rx(
            r"\b(?:active|current)\s+(?:DoD\s+)?(?:top\s+secret|secret|TS)\b(?:\s+(?:security\s+)?clearance)?"
        ),
    ),
    (
        "clearance",
        _rx(
            r"\b(?:top\s+secret|secret|security)\s+clearance\s+(?:is\s+)?(?:required|mandatory|needed)\b"
        ),
    ),
    (
        "clearance",
        _rx(
            r"\b(?:must\s+(?:have|hold|possess|obtain)|requires?)\s+(?:an?\s+)?(?:active\s+)?"
            r"(?:top\s+secret|secret|security)\s+clearance\b"
        ),
    ),
    (
        "clearance",
        _rx(
            r"\b(?:ability|able|eligib(?:le|ility))\s+to\s+(?:obtain|get|acquire|maintain)\s+"
            r"(?:and\s+maintain\s+)?(?:an?\s+)?(?:active\s+)?(?:DoD\s+|federal\s+|government\s+)?"
            r"(?:top\s+secret\s+|secret\s+|security\s+)?clearance\b"
        ),
    ),
]

_PUBLIC_TRUST = _rx(r"\bpublic\s+trust\b")

# Trigger words: something restriction-shaped that no rule read cleanly.
_CITIZEN_TRIGGER = _rx(r"\bcitizen(?:ship|s)?\b")
_EEO_CONTEXT = _rx(
    r"(?:regardless\s+of|without\s+regard\s+to|basis\s+of|based\s+on|discriminat|protected)"
    r"[^.]{0,120}$"
)
_CLEARANCE_TRIGGER = _rx(r"\b(?:(?:top\s+)?secret|security|government|DoD)\s+clearance\b")

# --------------------------------------------------------------------- #
# sponsorship rules

_WILL_NOT_RULES: list[re.Pattern] = [
    _rx(
        r"\b(?:unable|not\s+able|not\s+in\s+a\s+position|unwilling|not\s+willing|cannot|can\s?not|can't"
        r"|won't|will\s+not|do\s+not|does\s+not|don't|doesn't|are\s+not|is\s+not)\s+"
        r"(?:to\s+)?(?:currently\s+|now\s+)?(?:offer\s+|provide\s+|consider\s+|support\s+)?"
        rf"(?:{_VISA_WORD}\s+)?sponsor(?:ship|ing)?\b"
    ),
    _rx(
        rf"\b(?:{_VISA_WORD}\s+)?sponsorship\s+(?:is\s+|will\s+)?(?:not|un)\s*"
        r"(?:available|offered|provided|possible|be\s+(?:provided|offered|available))\b"
    ),
    _rx(rf"\bno\s+(?:{_VISA_WORD}\s+)?sponsorship\b"),
    _rx(rf"\bnot\s+eligible\s+for\s+(?:{_VISA_WORD}\s+)?sponsorship\b"),
    _rx(
        r"\bwithout\s+(?:the\s+need\s+for\s+)?(?:current\s+or\s+future\s+|any\s+|further\s+)?"
        rf"(?:{_VISA_WORD}\s+)?sponsorship\b"
    ),
    # "authorized to work in the US now or in the future" -- the qualifier,
    # not the authorization, is what rules sponsorship out.
    _rx(r"\bauthori[sz]ed\s+to\s+work\b[^.]{0,80}?\bnow\s+(?:and|or)\s+in\s+the\s+future\b"),
]

_WILL_RULES: list[re.Pattern] = [
    _rx(
        rf"\b(?:visa|{_H1B}|immigration|work\s+visa)\s+sponsorship\s+(?:is\s+)?"
        r"(?:available|offered|provided|supported)\b"
    ),
    _rx(
        r"\b(?:we|company|employer)\s+(?:will\s+|can\s+|do\s+|does\s+|are\s+able\s+to\s+|"
        r"are\s+happy\s+to\s+|are\s+willing\s+to\s+)?sponsors?\s+"
        rf"(?:{_H1B}|visas?|work\s+visas?|employment\s+visas?)\b"
    ),
    _rx(rf"\b(?:will|can)\s+sponsor\s+(?:{_H1B}|visas?|work\s+visas?)\b"),
    _rx(r"\b(?:willing|open)\s+to\s+sponsor(?:ing)?\b"),
    _rx(rf"\bsponsor(?:s|ship\s+for)?\s+{_H1B}\b"),
]

_SPONSOR_TRIGGER = _rx(
    rf"\b(?:{_H1B}|visa|immigration)\b[^.]{{0,40}}\bsponsor|\bsponsor(?:ship|ing)?\b[^.]{{0,40}}"
    rf"\b(?:{_H1B}|visas?|immigration)\b|\b(?:require|need)s?\s+(?:\w+\s+){{0,2}}sponsorship\b"
)
_WORK_AUTH = _rx(
    r"\b(?:authori[sz]ed|eligible|authorization)\s+to\s+work\b|\bwork\s+authori[sz]ation\b"
)

# --------------------------------------------------------------------- #
# OPT

_OPT = re.compile(r"\b(?:STEM\s+)?OPT\b(?![\s-]*(?i:in|out)\b)")
_CPT = re.compile(r"(?<!ICD-10 )(?<!ICD-10, )\bCPT\b(?!\s*(?:codes?|coding|/\s*ICD|,\s*ICD|®))")
_PRACTICAL_TRAINING = _rx(r"\b(?:optional|curricular)\s+practical\s+training\b")

# --------------------------------------------------------------------- #
# cap-exempt hint (company name only)

_CAP_EXEMPT_NAME = _rx(
    r"\b(?:university|college|community\s+college|institute\s+of\s+technology)\b"
)
# Structural for-profit markers: legal-entity suffixes and businesses that
# borrow the word ("University Credit Union"). NOT a list of real schools.
_FOR_PROFIT_MARKERS = _rx(
    r"\b(?:inc|incorporated|llc|l\.l\.c|corp|corporation|ltd|plc|lp|llp|holdings|"
    r"education\s+group|credit\s+union|bank|bookstore)\b\.?"
)
# Parked for the owner: may be exempt (affiliated / research), not decidable from a name.
_PARKED_ENTITIES = _rx(
    r"\b(?:hospital|medical\s+center|health\s+system|laboratory|national\s+lab)\b"
)


# --------------------------------------------------------------------- #


@dataclass(frozen=True)
class VisaSignals:
    restriction: str
    restriction_reason: str | None
    sponsorship_stance: str
    sponsorship_reason: str | None
    opt_mentioned: bool
    text_coverage: str
    cap_exempt_hint: str
    cap_exempt_reason: str | None


def text_coverage(description: str | None, description_full: str | None) -> str:
    """full when description_full is set; truncated for a description-only
    posting (Adzuna's ~500-char cap); empty when there is no body text."""
    if description_full and description_full.strip():
        return "full"
    if description and description.strip():
        return "truncated"
    return "empty"


def classify_restriction(
    text: str, key_requirements: list[str] | None = None
) -> tuple[str, str | None]:
    for req in key_requirements or []:
        if re.search(r"\bU\.?\s?S\.?\s+citizen", req or "", re.IGNORECASE):
            return "citizenship", "usajobs KeyRequirements"

    for label, rx in _CITIZENSHIP_RULES:
        m = rx.search(text)
        if m:
            return "citizenship", f'{label}: "{m.group(0)}"'

    negated: str | None = None
    for label, rx in _CLEARANCE_RULES:
        for m in rx.finditer(text):
            if _negated(text, m.start()):
                negated = negated or f'negated: "{_snippet(text, m, 15)}"'
                continue
            return "clearance", f'{label}: "{m.group(0)}"'

    m = _PUBLIC_TRUST.search(text)
    if m:
        return NONE_FOUND, f'public trust mentioned, not treated as a restriction: "{m.group(0)}"'
    if negated:
        return NONE_FOUND, negated
    for m in _CITIZEN_TRIGGER.finditer(text):
        before = text[max(0, m.start() - 120) : m.start()]
        after = text[m.end() : m.end() + 8]
        if _EEO_CONTEXT.search(before) or re.match(r"\s+status", after, re.IGNORECASE):
            continue  # EEO boilerplate: "... without regard to ... citizenship status"
        return NONE_FOUND, f'ambiguous: "{_snippet(text, m)}"'
    m = _CLEARANCE_TRIGGER.search(text)
    if m:
        if _negated(text, m.start()):
            return NONE_FOUND, f'negated: "{_snippet(text, m, 15)}"'
        return NONE_FOUND, f'ambiguous: "{_snippet(text, m)}"'
    return NONE_FOUND, None


def classify_sponsorship(text: str) -> tuple[str, str | None]:
    will_not = next((m for rx in _WILL_NOT_RULES if (m := rx.search(text))), None)
    will = None
    for rx in _WILL_RULES:
        for m in rx.finditer(text):
            if not _negated(text, m.start()):
                will = m
                break
        if will:
            break

    if will_not and will:
        return (
            NONE_FOUND,
            f'ambiguous: conflicting "{will_not.group(0)}" vs "{will.group(0)}"',
        )
    if will_not:
        return "will_not_sponsor", f'"{will_not.group(0)}"'
    if will:
        return "will_sponsor", f'"{will.group(0)}"'

    m = _SPONSOR_TRIGGER.search(text)
    if m:
        return NONE_FOUND, f'ambiguous: "{_snippet(text, m)}"'
    m = _WORK_AUTH.search(text)
    if m:
        return (
            NONE_FOUND,
            f'work authorization only, not a sponsorship stance (OPT is work authorization): "{m.group(0)}"',
        )
    return NONE_FOUND, None


def detect_opt(text: str) -> bool:
    return bool(_OPT.search(text) or _CPT.search(text) or _PRACTICAL_TRAINING.search(text))


def classify_cap_exempt(company_name: str | None) -> tuple[str, str | None]:
    name = normalize_text(company_name or "")
    m = _CAP_EXEMPT_NAME.search(name)
    if not m:
        return "unknown", None
    marker = _FOR_PROFIT_MARKERS.search(name)
    if marker:
        return "unknown", f'for-profit marker "{marker.group(0)}" in name'
    parked = _PARKED_ENTITIES.search(name)
    if parked:
        return "unknown", f'parked entity type "{parked.group(0)}" (hospital/lab rules undecided)'
    return "likely", f'name contains "{m.group(0)}"'


def classify_posting(
    title: str | None,
    description: str | None,
    description_full: str | None,
    company_name: str | None,
    key_requirements: list[str] | None = None,
) -> VisaSignals:
    body = description_full if description_full and description_full.strip() else description
    text = normalize_text(f"{title or ''}\n{body or ''}")
    restriction, restriction_reason = classify_restriction(text, key_requirements)
    stance, stance_reason = classify_sponsorship(text)
    cap_hint, cap_reason = classify_cap_exempt(company_name)
    return VisaSignals(
        restriction=restriction,
        restriction_reason=restriction_reason,
        sponsorship_stance=stance,
        sponsorship_reason=stance_reason,
        opt_mentioned=detect_opt(text),
        text_coverage=text_coverage(description, description_full),
        cap_exempt_hint=cap_hint,
        cap_exempt_reason=cap_reason,
    )
