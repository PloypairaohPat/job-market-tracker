"""Remote-work detection (Phase 2 upgrade over the Phase 1 title/location floor).

Signals, in precedence order (documented policy — see tests):
1. STRONG: the word "remote" in the title or location display name.
   Employers put it there deliberately; it wins over hybrid language in
   the description ("Remote" title + "hybrid options available" = remote).
2. Description POSITIVE patterns ("fully remote", "work from home", ...)
   count only if no NEGATION/HYBRID pattern also appears — boilerplate
   like "this is not a remote position" and hybrid arrangements must not
   inflate the remote rate.

Policy: **hybrid is not remote.** This metric tracks fully-remote
eligibility; hybrid gets its own treatment if/when a hybrid flag is
added. is_remote=False therefore means "not fully remote OR no signal",
which is why Phase 1 called this number a floor.
"""

from __future__ import annotations

import re

_STRONG = re.compile(r"\bremote\b", re.IGNORECASE)
_POSITIVE = re.compile(
    r"\b(fully[- ]remote|100%\s*remote|remote[- ](?:first|friendly|based|position|role|work|opportunity)"
    r"|work[- ]from[- ]home|wfh|telecommut\w+)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(
    r"\b(not?\s+(?:a\s+)?remote|no\s+remote\s+work|on[- ]?site\s+(?:only|required)"
    r"|hybrid|in[- ]office\s+required|must\s+be\s+on[- ]?site)\b",
    re.IGNORECASE,
)


def detect_remote(
    title: str | None,
    location_display: str | None = None,
    description: str | None = None,
) -> bool:
    if _STRONG.search(title or "") or _STRONG.search(location_display or ""):
        return True
    desc = description or ""
    if _POSITIVE.search(desc) and not _NEGATION.search(desc):
        return True
    return False
