"""Report 3: Who hires data analysts, and who has filed to sponsor them.

Which employers post analyst jobs, how concentrated hiring is, and how many
of those employers have a record of H-1B (LCA) filings for analytics roles.
Per market, never pooled. Narrative sections are [TO WRITE] placeholders
with this run's numbers; the kit writes no conclusions.

Views read (aggregate only; none has a job- or filing-level column):
  v_employer_postings           postings per employer, per market
  v_employer_roles              distinct roles (employer, normalized title) and
                                locations beside postings: a repost sensitivity
  v_employer_sponsorship_match  postings and employers matched to LCA history
  v_visa_outlook_summary        postings per visa-outlook bucket and reason
  v_matched_employer_lca_wages  offered wage on matched employers' filings
  v_lca_coverage, v_lca_monthly how complete each fiscal year in the filing
                                window is (Methods)

Guardrails (src/reports/guardrails.py, src/reports/lca_guardrails.py):
  - every number carries its n or denominator; LCA counts are labelled as
    filings, never hires or approvals; the wage is the offered wage on LCA
    filings, never what postings pay
  - an unmatched employer is "no match found"; "unknown" is never "no"
  - Methods prints the LCA caveats from src/visa/README.md
  - privacy: employers are named only beside their posting counts. Every
    sponsorship number is an aggregate, so nothing here recreates the
    private Visa outlook dashboard
  - with no LCA data loaded, the sponsorship sections say so and the hiring
    sections render as usual
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from src.reports.charts import grouped_barh
from src.reports.guardrails import Count, Rate
from src.reports.lca_guardrails import (
    BUCKET_LABELS,
    BUCKETS,
    LCA_CAVEATS,
    README_POINTER,
    UNMATCHED_LABEL,
    FilingCount,
    FilingWage,
    check_aggregate,
    check_caveats,
    check_sponsorship_text,
)
from src.reports.markdown import Doc
from src.reports.provenance import Provenance

SLUG = "employers-and-sponsorship"
TITLE = "Who hires data analysts, and who has filed to sponsor them"
VIEWS = (
    "v_employer_postings",
    "v_employer_roles",
    "v_employer_sponsorship_match",
    "v_visa_outlook_summary",
    "v_matched_employer_lca_wages",
    "v_lca_coverage",
    "v_lca_monthly",
)
MARKETS = ("commercial", "federal")
TOP_N = 10
# A pooled filing wage resting on fewer filings or employers than this is
# shown, but marked directional (parked threshold).
WAGE_MIN_FILINGS = 15
WAGE_MIN_EMPLOYERS = 5
# A month with fewer decisions than this share of its fiscal year's median
# month is flagged in Methods (parked threshold).
SPARSE_MONTH_SHARE = 0.10
CLOSED_BY_REQUIREMENT = ("posting restriction: citizenship", "posting restriction: clearance")
NOT_LOADED = "LCA data not loaded"
NO_ANALYTICS_NOTE = (
    "matched employers' filings in this window include no analytics-SOC H-1B filings"
)
FEDERAL_CAVEAT = (
    "**Federal LCA matches rarely bear on federal analyst jobs.** Federal civil-service "
    "positions generally require US citizenship, so an agency's LCA filings say little about "
    "its analyst postings. For the federal market the closed share, from the postings' own "
    "words, is the more relevant number."
)
ANALYTICS_FILINGS = "certified analytics-SOC H-1B LCA filings"


@dataclass(frozen=True)
class TopEmployer:
    name: str
    postings: Rate
    titles: int
    locations: int


@dataclass(frozen=True)
class Hiring:
    n_postings: int = 0
    n_employers: int = 0
    n_no_employer: int = 0
    top: tuple[TopEmployer, ...] = ()
    top_share: Rate = Rate(0, 0, unit="postings")
    tie_at_cutoff: bool = False
    n_roles: int = 0
    top_roles_share: Rate = Rate(0, 0, unit="roles")  # top TOP_N employers ranked by roles
    repeats: Rate = Rate(0, 0, unit="postings with a company")  # postings - roles


@dataclass(frozen=True)
class Match:
    n_postings: int = 0
    n_employers: int = 0
    postings: dict[str, Rate] = field(default_factory=dict)  # level -> Rate
    employers: dict[str, Rate] = field(default_factory=dict)


@dataclass(frozen=True)
class Outlook:
    n_postings: int = 0
    buckets: dict[str, Rate] = field(default_factory=dict)
    reasons: dict[str, dict[str, Rate]] = field(default_factory=dict)  # bucket -> reason -> Rate
    closed_by_requirement: Rate = Rate(0, 0, unit="closed postings")


@dataclass(frozen=True)
class Wages:
    filings: FilingCount = FilingCount(0, ANALYTICS_FILINGS)
    wage: FilingWage = FilingWage(0, 0)
    largest_filer: Rate = Rate(0, 0, unit="filings")
    unconvertible: int = 0

    @property
    def directional(self) -> bool:
        if not self.wage.n_filings:
            return False  # nothing to read at all, not "directional"
        return self.wage.n_filings < WAGE_MIN_FILINGS or self.wage.n_employers < WAGE_MIN_EMPLOYERS


@dataclass(frozen=True)
class FyCoverage:
    """How complete one fiscal year of LCA data is (v_lca_coverage, v_lca_monthly)."""

    fiscal_year: int
    n_cases: int = 0
    first: date | None = None
    last: date | None = None
    n_months: int = 0
    median_month: float = 0.0
    sparse: tuple[tuple[date, int], ...] = ()  # (month, n_cases) under SPARSE_MONTH_SHARE

    @property
    def partial(self) -> bool:
        return self.n_months < 12


@dataclass
class EmployersReport:
    hiring: dict[str, Hiring]
    lca_loaded: bool
    lca_rows: int
    window: tuple[int, int] | None
    match: dict[str, Match]
    outlook: dict[str, Outlook]
    wages: dict[str, Wages]
    coverage: tuple[FyCoverage, ...] = ()  # each FY of the filing window, oldest first


LEVELS = (
    ("matched", "an LCA filing of any status in the window"),
    ("certified_h1b", "≥ 1 certified H-1B LCA filing"),
    ("analytics_soc", "≥ 1 certified analytics-SOC H-1B LCA filing"),
)


def _hiring(frame: pd.DataFrame, roles: pd.DataFrame) -> Hiring:
    if frame.empty:
        return Hiring()
    total = int(frame["market_n_postings"].iloc[0])
    employers = frame[frame["employer_key"].notna()].merge(
        roles[["employer_key", "n_roles", "n_locations"]], on="employer_key", how="left"
    )
    employers[["n_roles", "n_locations"]] = employers[["n_roles", "n_locations"]].fillna(0)
    by_postings = employers.sort_values(
        ["n_postings", "employer_name", "employer_key"], ascending=[False, True, True]
    )
    top = by_postings.head(TOP_N)
    no_employer = int(frame.loc[frame["employer_key"].isna(), "n_postings"].sum())
    tie = (
        len(by_postings) > TOP_N
        and by_postings["n_postings"].iloc[TOP_N - 1] == by_postings["n_postings"].iloc[TOP_N]
    )
    n_roles = int(roles["market_n_roles"].iloc[0]) if not roles.empty else 0
    # its own ranking: the top TOP_N by roles can differ from the top by postings
    by_roles = employers.sort_values(
        ["n_roles", "employer_name", "employer_key"], ascending=[False, True, True]
    ).head(TOP_N)
    with_company = total - no_employer
    return Hiring(
        n_postings=total,
        n_employers=int(frame["market_n_employers"].iloc[0]),
        n_no_employer=no_employer,
        top=tuple(
            TopEmployer(
                r.employer_name,
                Rate(r.n_postings, total, unit="postings"),
                int(r.n_roles),
                int(r.n_locations),
            )
            for r in top.itertuples(index=False)
        ),
        top_share=Rate(int(top["n_postings"].sum()), total, unit="postings"),
        tie_at_cutoff=bool(tie),
        n_roles=n_roles,
        top_roles_share=Rate(int(by_roles["n_roles"].sum()), n_roles, unit="roles"),
        repeats=Rate(with_company - n_roles, with_company, unit="postings with a company"),
    )


def _match(row) -> Match:
    if row is None:
        return Match()
    return Match(
        n_postings=row.n_postings,
        n_employers=row.n_employers,
        postings={
            level: Rate(getattr(row, f"n_postings_{level}"), row.n_postings, unit="postings")
            for level, _ in LEVELS
        },
        employers={
            level: Rate(getattr(row, f"n_employers_{level}"), row.n_employers, unit="employers")
            for level, _ in LEVELS
        },
    )


def _outlook(frame: pd.DataFrame) -> Outlook:
    if frame.empty:
        return Outlook()
    total = int(frame["market_n_postings"].iloc[0])
    buckets = {
        b: Rate(int(frame.loc[frame["bucket"] == b, "n_postings"].sum()), total, unit="postings")
        for b in BUCKETS
    }
    reasons: dict[str, dict[str, Rate]] = {}
    for bucket in BUCKETS:
        rows = frame[frame["bucket"] == bucket].sort_values(
            ["n_postings", "bucket_reason"], ascending=[False, True]
        )
        n_bucket = buckets[bucket].numerator
        reasons[bucket] = {
            r.bucket_reason: Rate(r.n_postings, n_bucket, unit=f"{bucket} postings")
            for r in rows.itertuples(index=False)
        }
    closed = frame[frame["bucket"] == "closed"]
    by_requirement = int(
        closed.loc[closed["bucket_reason"].isin(CLOSED_BY_REQUIREMENT), "n_postings"].sum()
    )
    return Outlook(
        n_postings=total,
        buckets=buckets,
        reasons=reasons,
        closed_by_requirement=Rate(
            by_requirement, buckets["closed"].numerator, unit="closed postings"
        ),
    )


def _wages(row) -> Wages:
    if row is None or not row.n_filings:
        return Wages()

    def money(value):
        return None if pd.isna(value) else float(value)

    return Wages(
        filings=FilingCount(row.n_filings, ANALYTICS_FILINGS),
        wage=FilingWage(
            n_filings=row.n_filings_with_wage,
            n_employers=row.n_employers_with_wage,
            median=money(row.median_offered_annual_wage),
            p25=money(row.p25_offered_annual_wage),
            p75=money(row.p75_offered_annual_wage),
        ),
        largest_filer=Rate(row.largest_employer_n_filings, row.n_filings, unit="filings"),
        unconvertible=row.n_filings - row.n_filings_with_wage,
    )


def _coverage(
    window: tuple[int, int] | None, coverage: pd.DataFrame, monthly: pd.DataFrame
) -> tuple[FyCoverage, ...]:
    if window is None:
        return ()
    rows = {int(r.fiscal_year): r for r in coverage.itertuples(index=False)}
    out = []
    for fy in range(window[0], window[1] + 1):
        r = rows.get(fy)
        if r is None:
            out.append(FyCoverage(fy))
            continue
        months = monthly[monthly["fiscal_year"] == fy].sort_values("month")
        median = float(months["n_cases"].median()) if len(months) else 0.0
        sparse = tuple(
            (pd.Timestamp(m.month).date(), int(m.n_cases))
            for m in months.itertuples(index=False)
            if m.n_cases < SPARSE_MONTH_SHARE * median
        )
        out.append(
            FyCoverage(
                fiscal_year=fy,
                n_cases=int(r.n_cases),
                first=None if pd.isna(r.min_decision_date) else r.min_decision_date,
                last=None if pd.isna(r.max_decision_date) else r.max_decision_date,
                n_months=int(r.n_months_with_decisions),
                median_month=median,
                sparse=sparse,
            )
        )
    return tuple(out)


def compute(frames: dict[str, pd.DataFrame]) -> EmployersReport:
    check_aggregate(frames)
    postings = frames["v_employer_postings"]
    roles = frames["v_employer_roles"]
    match = {r.market: r for r in frames["v_employer_sponsorship_match"].itertuples(index=False)}
    outlook = frames["v_visa_outlook_summary"]
    wages = {r.market: r for r in frames["v_matched_employer_lca_wages"].itertuples(index=False)}
    any_match = next(iter(match.values()), None)
    lca_rows = int(any_match.lca_rows_loaded) if any_match is not None else 0
    window = None
    if lca_rows and not pd.isna(any_match.lca_window_end_fy):
        window = (int(any_match.lca_window_start_fy), int(any_match.lca_window_end_fy))
    return EmployersReport(
        hiring={
            m: _hiring(postings[postings["market"] == m], roles[roles["market"] == m])
            for m in MARKETS
        },
        lca_loaded=lca_rows > 0,
        lca_rows=lca_rows,
        window=window,
        match={m: _match(match.get(m)) for m in MARKETS},
        outlook={m: _outlook(outlook[outlook["market"] == m]) for m in MARKETS},
        wages={m: _wages(wages.get(m)) for m in MARKETS},
        coverage=_coverage(window, frames["v_lca_coverage"], frames["v_lca_monthly"]),
    )


# --------------------------------------------------------------------- #
# numbers for the narrative placeholders


def _not_loaded(label: str) -> tuple[str, str]:
    return (label, NOT_LOADED)


def headline_numbers(data: EmployersReport) -> list[tuple[str, object]]:
    numbers: list[tuple[str, object]] = []
    for m in MARKETS:
        h = data.hiring[m]
        numbers += [
            (f"{m.capitalize()} postings", Count(h.n_postings)),
            (f"{m.capitalize()} employers posting", Count(h.n_employers)),
            (
                f"{m.capitalize()} share of postings from the top {min(TOP_N, h.n_employers)} "
                "employers",
                h.top_share,
            ),
            (
                f"{m.capitalize()} share of distinct roles from the top "
                f"{min(TOP_N, h.n_employers)} employers by roles",
                h.top_roles_share,
            ),
        ]
    for m in MARKETS:
        label = f"{m.capitalize()} employers with ≥ 1 certified H-1B LCA filing"
        numbers.append(
            (label, data.match[m].employers["certified_h1b"])
            if data.lca_loaded
            else _not_loaded(label)
        )
    return numbers


def meaning_numbers(data: EmployersReport) -> list[tuple[str, object]]:
    numbers: list[tuple[str, object]] = []
    for m in MARKETS:
        h = data.hiring[m]
        numbers.append(
            (
                f"{m.capitalize()} postings with no company",
                Rate(h.n_no_employer, h.n_postings, unit="postings"),
            )
        )
    if not data.lca_loaded:
        return numbers + [_not_loaded("Every sponsorship number")]
    for m in MARKETS:
        mt, o = data.match[m], data.outlook[m]
        numbers += [
            (
                f"{m.capitalize()} postings at an employer with ≥ 1 certified H-1B LCA filing",
                mt.postings["certified_h1b"],
            ),
            (
                f"{m.capitalize()} postings in the unknown bucket",
                o.buckets.get("unknown", Rate(0, 0)),
            ),
            (
                f"{m.capitalize()} closed postings due to a citizenship or clearance requirement",
                o.closed_by_requirement,
            ),
        ]
    w = data.wages["commercial"]
    numbers += [
        ("Commercial: offered wage on matched employers' analytics-SOC LCA filings", w.wage),
        ("Commercial: share of those filings from the single largest filer", w.largest_filer),
    ]
    return numbers


def action_numbers(data: EmployersReport) -> list[tuple[str, object]]:
    if not data.lca_loaded:
        return [_not_loaded("Every sponsorship number")]
    numbers: list[tuple[str, object]] = []
    for m in MARKETS:
        numbers += [
            (
                f"{m.capitalize()} employers with ≥ 1 certified analytics-SOC H-1B LCA filing",
                data.match[m].employers["analytics_soc"],
            ),
            (
                f'{m.capitalize()} postings in the strong bucket (not a "yes")',
                data.outlook[m].buckets.get("strong", Rate(0, 0)),
            ),
            (
                f"{m.capitalize()} postings in the possible bucket",
                data.outlook[m].buckets.get("possible", Rate(0, 0)),
            ),
        ]
    return numbers


# --------------------------------------------------------------------- #
# rendering


def render(data: EmployersReport, provenance: Provenance, out_dir: Path) -> Path:
    out = out_dir / SLUG
    out.mkdir(parents=True, exist_ok=True)
    doc = Doc(
        TITLE,
        provenance,
        SLUG,
        subtitle=(
            "Phase 5 report 3. Who posts analyst jobs, how concentrated hiring is, and how many "
            "of those employers have filed LCAs for analytics roles. Aggregate and employer-level "
            "only: the per-job Visa outlook dashboard stays private."
        ),
    )

    doc.heading("Headline")
    doc.placeholder(
        "Headline",
        "One or two sentences on who hires data analysts and how concentrated that is, and, "
        "separately, how many of those employers have a record of LCA filings.",
        headline_numbers(data),
    )

    doc.heading("1. Who is compared")
    doc.paragraph(
        "**Commercial** is every Adzuna posting; **federal** is every USAJobs posting classified "
        "in scope. Each market is described on its own; nothing is pooled across them. Employers "
        "are grouped by their normalized name (`companies.normalized_name`)."
    )
    doc.table(
        ["Market", "Postings", "Employers posting", "Postings with no company"],
        [
            [m, h.n_postings, h.n_employers, Rate(h.n_no_employer, h.n_postings, unit="postings")]
            for m, h in data.hiring.items()
        ],
        caption="From `v_employer_postings`.",
    )

    doc.heading("2. Who posts analyst jobs")
    for m in MARKETS:
        h = data.hiring[m]
        doc.heading(f"{m.capitalize()}", level=3)
        if not h.top:
            doc.paragraph(f"No {m} postings with a company in this data.")
            continue
        k = min(TOP_N, h.n_employers)
        doc.bullets(
            [
                (f"Share of {m} postings from the top {k} employers", h.top_share),
                (
                    f"Share of distinct {m} roles from the top {k} employers by roles "
                    "(their own ranking)",
                    h.top_roles_share,
                ),
                (f"{m.capitalize()} postings that repeat a role already counted", h.repeats),
            ]
        )
        chart = grouped_barh(
            out / f"top-employers-{m}.png",
            [e.name for e in h.top],
            {m: [e.postings for e in h.top]},
            title=f"{m.capitalize()}: top {len(h.top)} employers by postings",
            xlabel="% of the market's postings",
            demo=provenance.is_demo,
        )
        doc.image(chart.name, f"Bars: the top {m} employers' share of postings")
        doc.table(
            ["Rank", "Employer", "Postings (share of the market)", "Distinct titles", "Locations"],
            [
                [f"#{i}", e.name, e.postings, e.titles, e.locations]
                for i, e in enumerate(h.top, start=1)
            ],
            caption=(
                "Postings with no company are never an employer; they stay in the denominator. "
                "Concentration counts postings, not hires. Distinct titles and locations are from "
                "`v_employer_roles`: many postings with few titles means the same role reposted."
            ),
        )
        if h.tie_at_cutoff:
            doc.paragraph(
                f"Several employers tie at place {TOP_N}; the share is the same whichever is shown "
                "(ties broken by name)."
            )

    doc.heading("3. Employers with LCA filing history")
    if not data.lca_loaded:
        _not_loaded_section(doc)
    else:
        start, end = data.window
        doc.paragraph(
            f"Postings and employers whose employer matches DOL's LCA disclosure data for "
            f"FY{start}–FY{end} (`v_employer_sponsorship`, `last_3_fy`, on the normalized "
            f"name). An employer without a match is **{UNMATCHED_LABEL}**: the name may differ, "
            "or the employer may file under another entity. The levels count LCA **filings**, "
            "which are not approvals or hires."
        )
        rows = []
        for level, label in LEVELS:
            rows.append(
                [label]
                + [
                    cell
                    for m in MARKETS
                    for cell in (data.match[m].postings[level], data.match[m].employers[level])
                ]
            )
        rows.append(
            [UNMATCHED_LABEL]
            + [
                cell
                for m in MARKETS
                for cell in (
                    Rate(
                        data.match[m].n_postings - data.match[m].postings["matched"].numerator,
                        data.match[m].n_postings,
                        unit="postings",
                    ),
                    Rate(
                        data.match[m].n_employers - data.match[m].employers["matched"].numerator,
                        data.match[m].n_employers,
                        unit="employers",
                    ),
                )
            ]
        )
        doc.table(
            [
                "Employer has",
                "Commercial postings",
                "Commercial employers",
                "Federal postings",
                "Federal employers",
            ],
            rows,
            caption=(
                f"From `v_employer_sponsorship_match`; levels are nested. {data.lca_rows:,} LCA "
                "filings loaded in all."
            ),
        )
        notes = [
            f"{m.capitalize()}: {NO_ANALYTICS_NOTE}." for m in MARKETS if _no_analytics(data, m)
        ]
        if notes:
            doc.bullets(notes)

    doc.heading("4. Visa outlook buckets (counts only)")
    if not data.lca_loaded:
        _not_loaded_section(doc)
    else:
        doc.paragraph(
            "The visa layer's buckets (`v_visa_outlook_summary`, thresholds unchanged), counted "
            'per market. **Closed** means the posting itself says no. **Strong** is not a "yes", '
            'and **unknown** is never a "no". This section is counts only; the per-job outlook '
            "stays in the private Visa outlook dashboard."
        )
        doc.table(
            ["Bucket", "Commercial", "Federal"],
            [
                [BUCKET_LABELS[b]] + [data.outlook[m].buckets.get(b, Rate(0, 0)) for m in MARKETS]
                for b in BUCKETS
            ],
            caption="Share of each market's in-scope postings.",
        )
        doc.bullets(
            [
                (
                    f"{m.capitalize()} closed postings due to a citizenship or clearance requirement",
                    data.outlook[m].closed_by_requirement,
                )
                for m in MARKETS
            ]
        )
        for bucket in ("closed", "unknown"):
            reasons = sorted({r for m in MARKETS for r in data.outlook[m].reasons.get(bucket, {})})
            if not reasons:
                continue
            doc.table(
                ["Why " + bucket, "Commercial", "Federal"],
                [
                    [reason]
                    + [
                        data.outlook[m]
                        .reasons.get(bucket, {})
                        .get(
                            reason,
                            Rate(
                                0,
                                data.outlook[m].buckets.get(bucket, Rate(0, 0)).numerator,
                                unit=f"{bucket} postings",
                            ),
                        )
                        for m in MARKETS
                    ]
                    for reason in reasons
                ],
                caption=f"Share of each market's {bucket} postings, by the rule that fired.",
            )

    doc.heading("5. Offered wage on matched employers' analytics-SOC LCA filings")
    if not data.lca_loaded:
        _not_loaded_section(doc)
    else:
        doc.paragraph(
            "The wage employers **offered on their LCA filings** for analytics SOC codes, pooled over "
            "the filings of employers that post in each market. It describes filings, never what "
            "the postings pay, and the biggest filers dominate it."
        )
        doc.table(
            [
                "Market",
                "Filings",
                "Offered annual wage on LCA filings",
                "Largest single filer's share",
                "Note",
            ],
            [
                [
                    m,
                    w.filings,
                    w.wage,
                    w.largest_filer,
                    _wage_note(w),
                ]
                for m, w in data.wages.items()
            ],
            caption="From `v_matched_employer_lca_wages`. Median and IQR, never the mean.",
        )

    doc.heading("What it means")
    doc.placeholder(
        "What it means",
        "What concentration and the filing record say about where analyst hiring is, and what "
        "the measurement can't show (unmatched names, truncated text, filings vs hires).",
        meaning_numbers(data),
    )
    doc.heading("What to do about it")
    doc.placeholder(
        "What to do about it",
        "What a job seeker on F-1 OPT should do with this, at aggregate level. Never a promise "
        "about one employer.",
        action_numbers(data),
    )

    _methods(doc, data)
    text = doc.render()
    check_sponsorship_text(text)
    check_caveats(text)
    path = out / "report.md"
    path.write_text(text)
    return path


def _no_analytics(data: EmployersReport, market: str) -> bool:
    """The market has matched employers, but none with an analytics-SOC filing."""
    employers_ = data.match[market].employers
    return bool(employers_) and (
        employers_["matched"].numerator > 0 and employers_["analytics_soc"].numerator == 0
    )


def _wage_note(w: Wages) -> str:
    notes = []
    if w.directional:
        notes.append(
            f"directional: under {WAGE_MIN_FILINGS} filings or {WAGE_MIN_EMPLOYERS} employers"
        )
    if w.unconvertible:
        notes.append(f"{w.unconvertible:,} filing(s) without an annual wage")
    return "; ".join(notes)


def _coverage_line(c: FyCoverage) -> str:
    if not c.n_cases:
        return f"FY{c.fiscal_year}: no LCA filings loaded"
    line = (
        f"FY{c.fiscal_year}: {c.n_months} of 12 months with decisions, {c.first} to {c.last}; "
        f"{c.n_cases:,} LCA filings loaded"
    )
    if c.partial:
        line += " (**partial fiscal year**: fewer than 12 months)"
    return line


def _not_loaded_section(doc: Doc) -> None:
    doc.paragraph(
        f"**{NOT_LOADED}.** `lca_cases` is empty, so no employer can be matched to a filing record. "
        f"Load DOL's LCA disclosure files ({README_POINTER}, steps 1–3), run `make views`, and "
        "render again. The hiring sections above don't need them."
    )


def _methods(doc: Doc, data: EmployersReport) -> None:
    doc.heading("Methods and caveats")
    doc.bullets(
        [
            *[(f"{m.capitalize()} postings", Count(data.hiring[m].n_postings)) for m in MARKETS],
            "Employers are grouped by `companies.normalized_name`; the display name is the first "
            "canonical name under it. Postings with no company are counted, never as an employer.",
            f"Concentration: the top {TOP_N} employers' share of the market's postings, ties broken "
            "by name (the share doesn't depend on the tie-break).",
            "Distinct roles (`v_employer_roles`): a role is an (employer, normalized title) pair; "
            "postings with no company have none. It's a sensitivity measure, not a dedup: "
            "identical titles at one employer can be different jobs (roles undercount), and small "
            "wording variants count separately (roles overcount). The role share ranks employers "
            "by roles, so its top "
            f"{TOP_N} can differ from the postings table; repeats are postings with a company "
            "minus their roles.",
            (
                "LCA filings loaded",
                FilingCount(data.lca_rows) if data.lca_loaded else NOT_LOADED,
            ),
            (
                "Filing window",
                f"FY{data.window[0]}–FY{data.window[1]} (the latest loaded FY and the two before it)"
                if data.window
                else NOT_LOADED,
            ),
            "Match: a posting's normalized employer name equals an LCA employer key in "
            "`v_employer_sponsorship` (`last_3_fy`). No fuzzy matching; near-misses go through "
            "`src/visa/sponsor_match.py`. Analytics SOC codes, the certified rule and the outlook "
            "thresholds are the visa layer's defaults (`sql/views/v_employer_sponsorship.sql`, "
            "`v_job_visa_outlook.sql`).",
            f"The offered wage is pooled over filings; under {WAGE_MIN_FILINGS} filings or "
            f"{WAGE_MIN_EMPLOYERS} employers it's marked directional.",
            "The outlook buckets count in-scope postings (`v_job_visa_outlook`); their total can "
            "differ from the posting count above while a posting's scope isn't classified yet.",
            FEDERAL_CAVEAT,
            (
                "Federal postings in the closed bucket",
                data.outlook["federal"].buckets.get("closed", Rate(0, 0))
                if data.lca_loaded
                else NOT_LOADED,
            ),
            "Privacy: employers are named only beside their posting counts. Every sponsorship "
            "number is an aggregate. No job titles, URLs or filing rows appear, and the per-job "
            "Visa outlook dashboard stays private.",
        ]
    )
    doc.heading("LCA coverage of the filing window", level=3)
    if not data.lca_loaded:
        doc.paragraph(f"**{NOT_LOADED}.**")
    else:
        doc.paragraph(
            "How complete each fiscal year in the window is (`v_lca_coverage`, `v_lca_monthly`). "
            "A partial year holds fewer filings than a full one, so the window is uneven and "
            "year-to-year comparisons aren't like for like."
        )
        doc.bullets([_coverage_line(c) for c in data.coverage])
        sparse = [
            f"FY{c.fiscal_year}, {month:%Y-%m}: {n:,} LCA filings decided, under "
            f"{SPARSE_MONTH_SHARE:.0%} of the fiscal year's median month ({c.median_month:,.0f}): "
            "unusually few decisions; cause not established"
            for c in data.coverage
            for month, n in c.sparse
        ]
        if sparse:
            doc.bullets(sparse)
    doc.heading("What LCA data can't tell you", level=3)
    doc.paragraph(f'From {README_POINTER}, "What this can\'t tell you":')
    doc.bullets(list(LCA_CAVEATS.values()))
