"""Salary quality assessment — flag, never discard.

Every job keeps its raw salary values exactly as ingested; this module
only assigns a quality flag so each downstream analysis can decide its
own inclusion rule (e.g. `WHERE salary_quality = 'ok'`).

Flags:
- None                       no salary disclosed (nothing to assess)
- 'ok'                       plausible annual figures
- 'suspect_hourly_as_annual' annual period but values in hourly range —
                             the classic contamination ($28 "per year")
- 'suspect_inverted'         min > max
- 'suspect_outlier_high'     implausibly high for the analyst market

Thresholds are deliberately conservative and documented; tune them in
ONE place (here) after auditing real data, never inline in analyses.
"""

from __future__ import annotations

# Below this, an "annual" figure is almost certainly an hourly/weekly rate.
HOURLY_CONTAMINATION_CEILING = 25_000
# Above this, an analyst-market minimum is presumed erroneous (fat-finger,
# total-comp-as-base, or currency confusion). Genuine exceptions exist;
# they can be rescued by a manual allowlist later if audits warrant.
OUTLIER_HIGH_FLOOR = 500_000


def assess_salary_quality(
    salary_min: int | None,
    salary_max: int | None,
    salary_period: str | None,
) -> str | None:
    if salary_min is None and salary_max is None:
        return None
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        return "suspect_inverted"
    top = salary_max if salary_max is not None else salary_min
    bottom = salary_min if salary_min is not None else salary_max
    if salary_period == "year" and top is not None and top < HOURLY_CONTAMINATION_CEILING:
        return "suspect_hourly_as_annual"
    if bottom is not None and bottom > OUTLIER_HIGH_FLOOR:
        return "suspect_outlier_high"
    return "ok"
