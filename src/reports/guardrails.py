"""Report guardrails as code: the rules from docs/phase_3_findings.md's
"Guardrails carried forward" lists that a renderer can enforce.

A report never prints a number directly. It wraps it in one of these types,
and the Markdown and chart renderers (src/reports/markdown.py, charts.py)
accept nothing else:

  Count  a raw count. A count is its own n.
  Rate   numerator, denominator, and optionally the view's own percentage.
         There is no way to build one without its denominator, and if the view
         computed the percentage, the numerator/denominator must reproduce it
         (catches a report quoting a rate against the wrong denominator).
  Ratio  a ratio or multiple (tags per job, "3.5x"), rendered with both terms.
  Stat   any other grouped number (a median, a length), rendered with its n.
  Gap    the percentage-point difference between two Rates, rendered with both.
  SalarySummary  median and IQR (never the mean) of ONE salary basis: employer-
         disclosed or Adzuna-predicted, never both pooled.

Plus:
  - SKILL_FLOOR: the skill drill-down reporting floors (n >= 15 commercial,
    n >= 5 federal; Investigation #2). `apply_floor` suppresses rows below it;
    `below_floor` flags a single group.
  - `skill_rate`: a share-of-jobs skill rate. Commercial (Adzuna) rates come
    out marked truncation-floored (the ~500-character description cap), and
    the renderers refuse to show them without that label.
  - The salary population rule: salary_quality = 'ok', USD, period = year.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd


class GuardrailError(ValueError):
    """A report tried to render a number in a way the guardrails forbid."""


# --------------------------------------------------------------------- #
# floors and labels

# Skill drill-down reporting floors (docs/phase_3_findings.md, Investigation #2,
# "Guardrails carried forward"). A floor is per market.
SKILL_FLOOR = {"commercial": 15, "federal": 5}

# Adzuna descriptions are capped at about 500 characters, so a commercial skill
# rate is a floor on the true rate, never complete recall.
TRUNCATION_LABEL = "truncation-floored"
TRUNCATED_MARKETS = frozenset({"commercial"})

# The only salary population a report may summarize (Investigation #1).
SALARY_FILTER = {"salary_quality": "ok", "salary_currency": "USD", "salary_period": "year"}
# Views that already apply SALARY_FILTER in their WHERE clause.
SALARY_CLEAN_VIEWS = frozenset({"v_commercial_salary_clean"})
SALARY_BASES = {"employer-disclosed": False, "Adzuna-predicted": True}


def floor_for(market: str) -> int:
    try:
        return SKILL_FLOOR[market]
    except KeyError:
        raise GuardrailError(
            f"no reporting floor for market {market!r} (known: {sorted(SKILL_FLOOR)})"
        ) from None


def below_floor(n: int, market: str) -> bool:
    return _count(n, "n") < floor_for(market)


def apply_floor(frame: pd.DataFrame, market: str, n_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split rows into (kept, suppressed) by the market's floor on `n_col`."""
    if n_col not in frame.columns:
        raise GuardrailError(f"column {n_col!r} not in frame: can't apply the n floor")
    mask = frame[n_col].map(lambda n: not below_floor(n, market))
    return frame[mask], frame[~mask]


# --------------------------------------------------------------------- #
# value types


def _count(value, what: str) -> int:
    """A non-negative integer, or GuardrailError (None, NaN, fractions, negatives)."""
    if value is None or isinstance(value, bool):
        raise GuardrailError(f"{what} is missing")
    if isinstance(value, numbers.Integral):
        result = int(value)
    elif isinstance(value, numbers.Real) and not math.isnan(value) and float(value).is_integer():
        result = int(value)
    else:
        raise GuardrailError(f"{what} must be a whole count, got {value!r}")
    if result < 0:
        raise GuardrailError(f"{what} can't be negative, got {result}")
    return result


def round_half_up(value: float, places: int = 1) -> float:
    """Postgres ROUND(numeric) semantics, so a recomputed rate matches the view's."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Count:
    n: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "n", _count(self.n, "count"))

    def render(self) -> str:
        return f"{self.n:,}"


@dataclass(frozen=True)
class Rate:
    """numerator of denominator, as a percentage.

    `pct` is the percentage a view already computed (rounded to one place). If
    given, it must agree with numerator/denominator to within the view's
    rounding: a mismatch means the report paired the rate with the wrong
    denominator, which is exactly the error this type exists to stop.
    """

    numerator: int
    denominator: int
    pct: float | None = None
    unit: str = ""
    truncation_floored: bool = False

    def __post_init__(self) -> None:
        num = _count(self.numerator, "rate numerator")
        den = _count(self.denominator, "rate denominator (a rate needs its denominator)")
        if num > den:
            raise GuardrailError(f"rate numerator {num} exceeds its denominator {den}")
        object.__setattr__(self, "numerator", num)
        object.__setattr__(self, "denominator", den)
        if self.pct is not None:
            pct = float(self.pct)
            if math.isnan(pct):
                raise GuardrailError("rate percentage is NaN")
            expected = 0.0 if den == 0 else 100.0 * num / den
            if abs(pct - expected) > 0.05 + 1e-9:
                raise GuardrailError(
                    f"the view says {pct}% but {num} of {den} is {expected:.2f}%: "
                    "wrong denominator?"
                )
            object.__setattr__(self, "pct", pct)

    @property
    def value(self) -> float | None:
        if self.denominator == 0:
            return None
        if self.pct is not None:
            return self.pct
        return round_half_up(100.0 * self.numerator / self.denominator)

    def render(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        if self.denominator == 0:
            return f"n/a (0 of 0{unit})"
        return f"{self.value:.1f}% ({self.numerator:,} of {self.denominator:,}{unit})"


@dataclass(frozen=True)
class Ratio:
    """numerator / denominator, rendered with both terms beside it."""

    numerator: float
    denominator: int
    places: int = 2
    suffix: str = ""
    terms: str = ""  # e.g. "tags / jobs"

    def __post_init__(self) -> None:
        if self.numerator is None or (
            isinstance(self.numerator, float) and math.isnan(self.numerator)
        ):
            raise GuardrailError("ratio numerator is missing")
        object.__setattr__(self, "denominator", _count(self.denominator, "ratio denominator"))

    def render(self) -> str:
        terms = f" {self.terms}" if self.terms else ""
        num = (
            f"{self.numerator:,}"
            if float(self.numerator).is_integer()
            else f"{self.numerator:,.{self.places}f}"
        )
        if self.denominator == 0:
            return f"n/a ({num} / 0{terms})"
        value = self.numerator / self.denominator
        return f"{value:,.{self.places}f}{self.suffix} ({num} / {self.denominator:,}{terms})"


@dataclass(frozen=True)
class Stat:
    """A grouped number other than a count or rate (a median, a length): with its n."""

    value: float
    n: int
    fmt: str = "{:,.0f}"
    prefix: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "n", _count(self.n, "n behind a grouped number"))
        if self.value is None or (isinstance(self.value, float) and math.isnan(self.value)):
            if self.n:
                raise GuardrailError("grouped number is missing but its n isn't 0")

    def render(self) -> str:
        if self.n == 0 or self.value is None:
            return "n/a (n=0)"
        return f"{self.prefix}{self.fmt.format(self.value)} (n={self.n:,})"


@dataclass(frozen=True)
class Gap:
    """Percentage-point difference a - b, shown with both rates."""

    a: Rate
    b: Rate

    def __post_init__(self) -> None:
        if not isinstance(self.a, Rate) or not isinstance(self.b, Rate):
            raise GuardrailError("a gap is computed between two Rates, each with its denominator")

    @property
    def points(self) -> float | None:
        if self.a.value is None or self.b.value is None:
            return None
        return round_half_up(self.a.value - self.b.value)

    def render(self) -> str:
        if self.points is None:
            return f"n/a ({self.a.render()} vs {self.b.render()})"
        return f"{self.points:+.1f} pp ({self.a.render()} vs {self.b.render()})"

    @property
    def truncation_floored(self) -> bool:
        return self.a.truncation_floored or self.b.truncation_floored


def skill_rate(numerator: int, denominator: int, market: str, pct: float | None = None) -> Rate:
    """A share-of-jobs skill rate. Commercial rates are marked truncation-floored."""
    floor_for(market)  # unknown market -> GuardrailError
    return Rate(
        numerator,
        denominator,
        pct=pct,
        unit="jobs",
        truncation_floored=market in TRUNCATED_MARKETS,
    )


# --------------------------------------------------------------------- #
# salary


@dataclass(frozen=True)
class SalarySummary:
    """Median and IQR of one salary basis. There is deliberately no mean."""

    basis: str
    n: int
    median: float | None
    p25: float | None
    p75: float | None

    def render(self) -> str:
        if self.n == 0:
            return f"n/a (n=0, {self.basis})"
        return (
            f"${self.median:,.0f} (IQR ${self.p25:,.0f}–${self.p75:,.0f}; "
            f"n={self.n:,}, {self.basis})"
        )


def check_salary_population(frame: pd.DataFrame, source_view: str) -> None:
    """Refuse anything but the clean population: salary_quality='ok', USD, year."""
    present = [c for c in SALARY_FILTER if c in frame.columns]
    if source_view not in SALARY_CLEAN_VIEWS and len(present) < len(SALARY_FILTER):
        raise GuardrailError(
            f"{source_view!r} isn't a clean-salary view ({sorted(SALARY_CLEAN_VIEWS)}) and doesn't "
            "carry salary_quality / salary_currency / salary_period to check: refusing "
            "(salary is reported only for salary_quality='ok', USD, year)"
        )
    for column in present:
        bad = frame[frame[column] != SALARY_FILTER[column]]
        if len(bad):
            raise GuardrailError(
                f"{len(bad)} row(s) with {column} != {SALARY_FILTER[column]!r}: salary is "
                "reported only for salary_quality='ok', USD, year"
            )


def summarize_salary(
    frame: pd.DataFrame,
    basis: str,
    source_view: str,
    value_col: str = "salary_midpoint",
) -> SalarySummary:
    """Median and IQR for ONE basis ("employer-disclosed" or "Adzuna-predicted").

    There is no pooled option: disclosed and predicted salaries are never
    summarized together. Linear-interpolated quartiles, like Postgres's
    percentile_cont.
    """
    if basis not in SALARY_BASES:
        raise GuardrailError(
            f"salary basis must be one of {sorted(SALARY_BASES)}, got {basis!r}: "
            "disclosed and predicted salaries are never pooled"
        )
    if "salary_is_predicted" not in frame.columns:
        raise GuardrailError(
            "frame has no salary_is_predicted column: can't separate employer-disclosed "
            "from Adzuna-predicted salaries, refusing to pool them"
        )
    if value_col not in frame.columns:
        raise GuardrailError(f"column {value_col!r} not in frame")
    check_salary_population(frame, source_view)
    flags = frame["salary_is_predicted"]
    if flags.isna().any():
        raise GuardrailError("salary_is_predicted is NULL on some rows: can't assign a basis")
    values = frame.loc[flags == SALARY_BASES[basis], value_col].dropna().astype(float)
    if values.empty:
        return SalarySummary(basis, 0, None, None, None)
    p25, median, p75 = values.quantile([0.25, 0.5, 0.75]).tolist()
    return SalarySummary(basis, len(values), median, p25, p75)
