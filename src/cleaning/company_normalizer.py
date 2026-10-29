"""Company name normalization — built as a LAYER, never a destructive merge.

Three tiers, exactly as PROJECT_GUIDE.md prescribes:

1. **Deterministic rules** (this module): lowercase, strip legal
   suffixes (Inc/LLC/Corp/...), strip a leading "The", collapse
   punctuation/whitespace. Handles the bulk of duplication safely.
2. **Curated aliases** (data/company_aliases.json): unambiguous
   same-employer mappings (Facebook -> meta). Checked before AND after
   rule-stripping so both raw and stripped forms resolve.
3. **Fuzzy candidates for MANUAL review** (`find_merge_candidates`):
   near-matches and containments are *proposed* to a CSV, never
   auto-applied. Approved pairs get promoted into the alias file.

The output `normalized_name` is a lowercase grouping KEY stored on
`companies`; display names for reporting are chosen at query time (most
frequent raw name per key). Raw names are never modified — the whole
layer can be recomputed or discarded at any time.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

ALIASES_PATH = Path(__file__).parent / "data" / "company_aliases.json"

_LEGAL_SUFFIXES = (
    "incorporated",
    "corporation",
    "company",
    "limited",
    "holdings",
    "inc",
    "llc",
    "pllc",
    "llp",
    "ltd",
    "corp",
    "plc",
    "gmbh",
    "lp",
    "pc",
    "co",
)
# one suffix token at the end, optionally preceded by comma/period/space
_SUFFIX_RE = re.compile(
    r"[\s,.]+(?:" + "|".join(_LEGAL_SUFFIXES) + r")\.?$",
    re.IGNORECASE,
)
_THE_PREFIX = re.compile(r"^the\s+", re.IGNORECASE)
_PUNCT = re.compile(r"[.,'’\"]")
_WS = re.compile(r"\s+")


@lru_cache(maxsize=1)
def _aliases() -> dict[str, str]:
    raw = json.loads(ALIASES_PATH.read_text())["aliases"]
    return {k: v for k, v in raw.items() if not k.startswith("_comment")}


def rule_key(raw: str) -> str:
    """The rules alone, without the alias map: lowercase, legal suffixes, a
    leading "The", punctuation and whitespace."""
    s = _WS.sub(" ", raw.strip()).lower()
    # strip legal suffixes repeatedly ("Acme Holdings LLC" -> "acme")
    while True:
        stripped = _SUFFIX_RE.sub("", s)
        if stripped == s or not stripped:
            break
        s = stripped
    s = _THE_PREFIX.sub("", s)
    return _WS.sub(" ", _PUNCT.sub(" ", s)).strip()


def normalize_company_name(raw: str) -> str:
    """Reduce a raw company string to its lowercase grouping key."""
    s = _WS.sub(" ", raw.strip()).lower()
    if s in _aliases():
        return _aliases()[s]
    s = rule_key(s)
    return _aliases().get(s, s)


DEFAULT_SIMILARITY_CUTOFF = 0.88


def classify_pair(
    a: str, b: str, similarity_cutoff: float = DEFAULT_SIMILARITY_CUTOFF
) -> dict | None:
    """The containment / fuzzy rule for one pair of distinct normalized names.

    Returns {relation, similarity} or None. Shared by `find_merge_candidates`
    and the cross-set sponsor matcher (src/visa/sponsor_match.py) so both
    propose candidates by exactly the same rules and cutoff.
    """
    if b.startswith(a + " ") or a.startswith(b + " "):
        return {"relation": "containment", "similarity": 1.0}
    ratio = SequenceMatcher(None, a, b).ratio()
    if ratio >= similarity_cutoff:
        return {"relation": "fuzzy", "similarity": round(ratio, 3)}
    return None


def find_merge_candidates(
    names: list[str],
    similarity_cutoff: float = DEFAULT_SIMILARITY_CUTOFF,
) -> list[dict]:
    """Propose near-duplicate normalized names for MANUAL review.

    Returns dicts: {name_a, name_b, relation, similarity}. Relations:
    - 'containment': one name starts with the other + a space
      ("deloitte" / "deloitte consulting llp"-stripped) — the classic
      parent/subsidiary or short/long form.
    - 'fuzzy': SequenceMatcher ratio >= cutoff (typos, minor variants).

    O(n^2) with a first-letter bucket optimization — fine for the tens
    of thousands of names this project will see; revisit with a proper
    blocking strategy if that assumption breaks.
    """
    uniq = sorted(set(names))
    candidates: list[dict] = []
    for i, a in enumerate(uniq):
        for b in uniq[i + 1 :]:
            if b[0] != a[0]:
                break  # sorted: no more shared-first-letter pairs for `a`
            match = classify_pair(a, b, similarity_cutoff)
            if match:
                candidates.append({"name_a": a, "name_b": b, **match})
    return candidates
