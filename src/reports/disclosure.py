"""Report 2: How much employers disclose (Phase 3 Investigation #3).

How much a data-analyst posting tells a candidate, per market, keeping the
fields that measure employer disclosure apart from the fields that measure
this project's own classifiers. Narrative sections are [TO WRITE]
placeholders with this run's numbers; the kit writes no conclusions.

Views read (and nothing else):
  v_field_completeness         per-market percentages (the source of truth)
  v_field_completeness_counts  the counts behind them; every rate is
                               rebuilt from these and checked against the
                               percentage view

Guardrails applied (src/reports/guardrails.py and the findings doc):
  - every rate shows its numerator and denominator; never pooled across markets
  - salary has two layers: any figure present vs employer-disclosed (the rest
    of commercial is Adzuna's model estimate)
  - commercial skills-present is truncation-floored
  - instrument-limited fields (seniority, metro, remote) get their own section
    and are never charted beside the measured fields; federal remote is shown
    as not measurable, never as a 0% rate
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.reports.charts import grouped_barh
from src.reports.guardrails import TRUNCATION_LABEL, Count, GuardrailError, Rate, skill_rate
from src.reports.markdown import Doc
from src.reports.provenance import Provenance

SLUG = "how-much-employers-disclose"
TITLE = "How much employers disclose"
VIEWS = ("v_field_completeness", "v_field_completeness_counts")
MARKETS = ("commercial", "federal")


@dataclass(frozen=True)
class Field:
    key: str  # n_<key> in the counts view, pct_<key> in the percentage view
    name: str
    layer: str
    measured: bool
    mechanism: str = ""  # why an instrument-limited field measures us, not employers


FIELDS = (
    Field("salary_present", "Salary", "any figure present", True),
    Field("salary_disclosed", "Salary", "employer-disclosed", True),
    Field("salary_predicted", "Salary", "Adzuna model estimate", True),
    Field("skill_present", "Skills", "≥ 1 skill tag (any confidence)", True),
    Field("location_present", "Location", "any location parsed", True),
    Field("company_present", "Company", "company present", True),
    Field("posted_at_present", "Posted date", "present", True),
    Field(
        "seniority_present",
        "Seniority",
        "title carries an explicit level",
        False,
        "the classifier reads the job title only (src/cleaning/seniority.py); a level stated "
        "only in the description is invisible to it",
    ),
    Field(
        "metro_present",
        "Metro",
        "in the tracked 8-city + DC list",
        False,
        "a lookup against a curated allowlist (src/cleaning/metro.py), never a default; real "
        "cities outside the list count as absent. Location present is the disclosure rate",
    ),
    Field(
        "remote_true",
        "Remote",
        "flagged remote",
        False,
        "the classifier scans `jobs.description` only (src/cleaning/apply_cleaning.py); "
        "federal telework policy sits in `description_full`, so federal is not measurable",
    ),
)
BY_KEY = {f.key: f for f in FIELDS}
CHARTED = ("salary_present", "salary_disclosed", "skill_present")
# (market, field) pairs the instrument can't measure: rendered as text, never a rate
NOT_MEASURABLE = frozenset({("federal", "remote_true")})
NOT_MEASURABLE_TEXT = "not measurable"


def check_charted(keys) -> None:
    """Instrument-limited fields are never charted beside the measured ones."""
    limited = [k for k in keys if not BY_KEY[k].measured]
    if limited:
        raise GuardrailError(f"instrument-limited field(s) {limited} can't be charted")


@dataclass
class Disclosure:
    n_jobs: dict[str, int]
    rates: dict[tuple[str, str], Rate]  # (market, field key) -> Rate


def _rate(market: str, key: str, n: int, n_jobs: int, pct) -> Rate:
    if key == "skill_present":  # commercial skills-present is truncation-floored
        return skill_rate(n, n_jobs, market, pct=pct)
    return Rate(n, n_jobs, pct=pct, unit="jobs")


def compute(frames: dict[str, pd.DataFrame]) -> Disclosure:
    pct = {r.market: r for r in frames["v_field_completeness"].itertuples(index=False)}
    counts = {r.market: r for r in frames["v_field_completeness_counts"].itertuples(index=False)}
    if set(pct) != set(counts):
        raise GuardrailError(
            f"the two completeness views disagree on markets: {sorted(pct)} vs {sorted(counts)}"
        )
    n_jobs: dict[str, int] = {m: 0 for m in MARKETS}
    rates: dict[tuple[str, str], Rate] = {}
    for market in MARKETS:
        c = counts.get(market)
        if c is None:
            for f in FIELDS:
                rates[(market, f.key)] = _rate(market, f.key, 0, 0, None)
            continue
        if c.n_jobs != pct[market].n_jobs:
            raise GuardrailError(f"{market}: n_jobs differs between the completeness views")
        n_jobs[market] = c.n_jobs
        for f in FIELDS:
            # the percentage view's own figure, where it has one, must reproduce
            view_pct = getattr(pct[market], f"pct_{f.key}", None)
            rates[(market, f.key)] = _rate(
                market, f.key, getattr(c, f"n_{f.key}"), c.n_jobs, view_pct
            )
    return Disclosure(n_jobs=n_jobs, rates=rates)


def cell(data: Disclosure, market: str, key: str):
    if (market, key) in NOT_MEASURABLE:
        return NOT_MEASURABLE_TEXT
    return data.rates[(market, key)]


def _label(f: Field) -> str:
    return f"{f.name}: {f.layer}"


# --------------------------------------------------------------------- #
# numbers for the narrative placeholders


def headline_numbers(data: Disclosure) -> list[tuple[str, object]]:
    numbers: list[tuple[str, object]] = [
        (f"{m.capitalize()} jobs", Count(data.n_jobs[m])) for m in MARKETS
    ]
    for key in ("salary_disclosed", "salary_present", "skill_present"):
        for market in MARKETS:
            numbers.append(
                (f"{market.capitalize()} {_label(BY_KEY[key])}", cell(data, market, key))
            )
    return numbers


def meaning_numbers(data: Disclosure) -> list[tuple[str, object]]:
    numbers: list[tuple[str, object]] = [
        (
            "Commercial salary that is Adzuna's model estimate",
            data.rates[("commercial", "salary_predicted")],
        ),
        (
            "Federal salary that is Adzuna's model estimate",
            data.rates[("federal", "salary_predicted")],
        ),
    ]
    for key in ("location_present", "metro_present", "seniority_present", "remote_true"):
        for market in MARKETS:
            numbers.append(
                (f"{market.capitalize()} {_label(BY_KEY[key])}", cell(data, market, key))
            )
    return numbers


def action_numbers(data: Disclosure) -> list[tuple[str, object]]:
    return [
        (
            "Commercial postings with an employer-disclosed salary",
            data.rates[("commercial", "salary_disclosed")],
        ),
        ("Commercial postings with ≥ 1 skill tag", data.rates[("commercial", "skill_present")]),
        ("Commercial postings with any location", data.rates[("commercial", "location_present")]),
    ]


# --------------------------------------------------------------------- #
# rendering


def render(data: Disclosure, provenance: Provenance, out_dir: Path) -> Path:
    out = out_dir / SLUG
    out.mkdir(parents=True, exist_ok=True)
    doc = Doc(
        TITLE,
        provenance,
        SLUG,
        subtitle=(
            "Phase 5 report 2. Regenerates Phase 3 Investigation #3 "
            "(docs/phase_3_findings.md) from the SQL views."
        ),
    )

    doc.heading("Headline")
    doc.placeholder(
        "Headline",
        "One or two sentences on how much a posting tells a candidate. Base it on the "
        "measured fields (section 2), never the instrument-limited ones.",
        headline_numbers(data),
    )

    doc.heading("1. Who is compared")
    doc.paragraph(
        "**Commercial** is every Adzuna posting; **federal** is every USAJobs posting "
        "classified in scope (`jobs.in_scope`). Every figure is per market. A blended "
        '"% populated" would be a category error: federal pay bands are disclosed by law, '
        "commercial salaries by choice."
    )
    doc.table(["Market", "Jobs"], [[m, data.n_jobs[m]] for m in MARKETS])

    doc.heading("2. Measured fields (what employers disclose)")
    measured = [f for f in FIELDS if f.measured]
    check_charted(CHARTED)
    chart = grouped_barh(
        out / "measured-fields.png",
        [_label(BY_KEY[k]) for k in CHARTED],
        {m: [data.rates[(m, k)] for k in CHARTED] for m in MARKETS},
        title="Share of each market's postings carrying the field",
        xlabel=f"% of the market's jobs (commercial skills: {TRUNCATION_LABEL})",
        demo=provenance.is_demo,
    )
    doc.image(
        chart.name, "Grouped bars: salary present, salary disclosed, skills present, by market"
    )
    doc.table(
        ["Field", "Layer", "Commercial", "Federal"],
        [
            [f.name, f.layer, cell(data, "commercial", f.key), cell(data, "federal", f.key)]
            for f in measured
        ],
        caption=(
            "From `v_field_completeness_counts`, each rate checked against `v_field_completeness`. "
            f"Commercial skills present is {TRUNCATION_LABEL}: Adzuna's ~500-character cap hides "
            "skills, so an absent tag is often a recall failure, not a skill-free posting."
        ),
    )
    doc.paragraph(
        "Salary has two layers. Adzuna returns a salary for nearly every posting, filling the "
        'gaps with its own model\'s estimate, so "any figure present" overstates disclosure: '
        "**employer-disclosed** is the market fact. Federal pay bands are never modelled."
    )

    doc.heading("3. Instrument-limited fields (what our classifiers can see)")
    doc.paragraph(
        "These measure this project's instruments, not employer disclosure, so they are kept "
        "out of the chart and shown here with the mechanism that limits each one. Don't read "
        "them beside the measured fields."
    )
    doc.table(
        ["Field", "Layer", "Commercial", "Federal", "Why it's instrument-limited"],
        [
            [
                f.name,
                f.layer,
                cell(data, "commercial", f.key),
                cell(data, "federal", f.key),
                f.mechanism,
            ]
            for f in FIELDS
            if not f.measured
        ],
        caption="Instrument-limited: from `v_field_completeness_counts`, checked against `v_field_completeness`.",
    )

    doc.heading("What it means")
    doc.placeholder(
        "What it means",
        "What the gap between present and disclosed (and between measured and "
        "instrument-limited) says about what a candidate can learn from a posting.",
        meaning_numbers(data),
    )
    doc.heading("What to do about it")
    doc.placeholder(
        "What to do about it",
        "What a job seeker (or this project's instruments) should do about it.",
        action_numbers(data),
    )

    doc.heading("Methods and caveats")
    doc.bullets(
        [
            ("Commercial jobs (every Adzuna posting)", Count(data.n_jobs["commercial"])),
            ("Federal jobs (USAJobs postings classified in scope)", Count(data.n_jobs["federal"])),
            "Never pooled across markets: every rate is one market's, with its own denominator.",
            "Every rate is rebuilt from `v_field_completeness_counts` and checked against the "
            "percentage `v_field_completeness` computes; a mismatch stops the report.",
            "Skills present counts a tag at any confidence, as `v_field_completeness` does; "
            "report 1 (commercial vs federal skills) uses confidence ≥ 0.8, so its tagged-job "
            "counts can be lower.",
            f"Commercial skills present is **{TRUNCATION_LABEL}** (Adzuna's ~500-character cap).",
            "Instrument-limited fields come with their mechanism and are never charted. Federal "
            f'remote is shown as "{NOT_MEASURABLE_TEXT}", never as a rate.',
            "The recon samples behind the instrument-limited labels (for example the seniority "
            "sample) are raw counts in docs/findings_field_completeness.md; they aren't in a view "
            "and aren't regenerated here.",
            "Sources: `sql/views/v_field_completeness.sql`, `v_field_completeness_counts.sql`; "
            "docs/phase_3_findings.md (Investigation #3); docs/findings_field_completeness.md.",
        ]
    )
    path = out / "report.md"
    path.write_text(doc.render())
    return path
