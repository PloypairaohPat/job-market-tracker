"""Report 1: Commercial vs federal skill demand (Phase 3 Investigation #2).

Regenerates the investigation's tables, chart and methods section from four
views, and leaves the narrative (headline, what it means, what to do about
it) as [TO WRITE] placeholders with this run's numbers beside each one. It
writes no conclusions: those are the owner's, on real data.

Views read (and nothing else):
  v_skill_category_composition  share of each market's skill tags by category
                                (the primary comparison)
  v_skill_text_basis            what text the extractor read; n_tags is the
                                composition's denominator
  v_skill_top_by_source         the skill drill-down (directional texture)
  v_federal_skill_by_admission  the Statistics-tag circularity check

Guardrails applied (src/reports/guardrails.py):
  - every number carries its n or denominator; the composition percentages
    are checked against v_skill_text_basis.n_tags
  - drill-down rows below n >= 15 (commercial) / n >= 5 (federal) are not
    shown, and the report says how many were suppressed; composition
    categories below those floors are shown but marked
  - commercial skill rates are labelled truncation-floored
  - every number is per market, never pooled
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.reports.charts import FLAG_MARK, grouped_barh
from src.reports.guardrails import (
    TRUNCATION_LABEL,
    Count,
    Gap,
    Rate,
    Ratio,
    Stat,
    apply_floor,
    below_floor,
    floor_for,
    skill_rate,
)
from src.reports.markdown import Doc
from src.reports.provenance import Provenance

SLUG = "commercial-vs-federal-skills"
TITLE = "Commercial vs federal skill demand"
VIEWS = (
    "v_skill_category_composition",
    "v_skill_text_basis",
    "v_skill_top_by_source",
    "v_federal_skill_by_admission",
)
MARKETS = ("commercial", "federal")

# Facts about the instrument, kept in step with the views by tests.
SKILL_CONFIDENCE = 0.8  # every skill view's fixed threshold
NEAR_CAP_CHARS = 480  # v_skill_text_basis.n_near_cap
CIRCULARITY_SKILL = "Statistics"
# Taxonomy entries added while reading federal postings in Investigation #2
# (docs/findings_commercial_vs_federal_skills.md, "Taxonomy provenance").
FEDERAL_FITTED = {
    "SQL": "alias 'structured query language' added",
    "SPSS": "new skill",
    "GIS": "new skill",
    "SSIS": "new skill",
    "SSRS": "new skill",
}
FITTED_MARK = "†"
DRILLDOWN_ROWS = 15  # most skills shown per market, above the floor
HEADLINE_GAPS = 3
ACTION_SKILLS = 5


@dataclass(frozen=True)
class Basis:
    """One market's row of v_skill_text_basis (zeros if the market is absent)."""

    market: str
    n_jobs: int = 0
    n_full_text: int = 0
    n_near_cap: int = 0
    p25_chars: float | None = None
    median_chars: float | None = None
    p75_chars: float | None = None
    n_jobs_tagged: int = 0
    n_tags: int = 0

    @property
    def text_length(self) -> Stat:
        iqr = None if self.p25_chars is None else (self.p25_chars, self.p75_chars)
        return Stat(self.median_chars, self.n_jobs, fmt="{:,.0f}", iqr=iqr)


@dataclass(frozen=True)
class SkillRow:
    name: str
    category: str
    rate: Rate

    @property
    def label(self) -> str:
        return f"{self.name} {FITTED_MARK}" if self.name in FEDERAL_FITTED else self.name


@dataclass
class SkillDemand:
    basis: dict[str, Basis]
    categories: list[str]
    composition: dict[tuple[str, str], Rate]
    flagged: frozenset[tuple[str, str]]
    drilldown: dict[str, list[SkillRow]]
    suppressed: dict[str, int]
    routes: list[tuple[str, Rate]]  # (admission route, Statistics-tagged of route jobs)
    fitted_in_federal: dict[str, int] = field(default_factory=dict)  # name -> federal jobs tagged


def _basis(frame: pd.DataFrame) -> dict[str, Basis]:
    out = {m: Basis(m) for m in MARKETS}
    for row in frame.itertuples(index=False):
        out[row.market] = Basis(
            market=row.market,
            n_jobs=row.n_jobs,
            n_full_text=row.n_full_text,
            n_near_cap=row.n_near_cap,
            p25_chars=float(row.p25_text_chars),
            median_chars=float(row.median_text_chars),
            p75_chars=float(row.p75_text_chars),
            n_jobs_tagged=row.n_jobs_tagged,
            n_tags=row.n_tags,
        )
    return out


def compute(frames: dict[str, pd.DataFrame]) -> SkillDemand:
    basis = _basis(frames["v_skill_text_basis"])

    comp = frames["v_skill_category_composition"]
    composition: dict[tuple[str, str], Rate] = {}
    for row in comp.itertuples(index=False):
        # pct_of_tags must reproduce from n_tags / the market's total tags
        composition[(row.market, row.category)] = Rate(
            row.n_tags, basis[row.market].n_tags, pct=row.pct_of_tags, unit="tags"
        )
    categories = sorted(
        {category for _, category in composition},
        key=lambda c: (
            -(composition.get(("commercial", c)) or Rate(0, 1)).numerator
            / max(basis["commercial"].n_tags, 1),
            -(composition.get(("federal", c)) or Rate(0, 1)).numerator
            / max(basis["federal"].n_tags, 1),
            c,
        ),
    )
    for market in MARKETS:
        for category in categories:
            composition.setdefault((market, category), Rate(0, basis[market].n_tags, unit="tags"))
    flagged = frozenset(
        (market, category)
        for (market, category), rate in composition.items()
        if basis[market].n_tags and below_floor(rate.numerator, market)
    )

    top = frames["v_skill_top_by_source"]
    drilldown: dict[str, list[SkillRow]] = {}
    suppressed: dict[str, int] = {}
    for market in MARKETS:
        rows = top[top["market"] == market].sort_values(
            ["n_jobs_tagged", "name"], ascending=[False, True]
        )
        kept, dropped = apply_floor(rows, market, "n_jobs_tagged")
        drilldown[market] = [
            SkillRow(
                r.name,
                r.category,
                skill_rate(r.n_jobs_tagged, r.market_n_jobs, market, pct=r.pct_of_jobs),
            )
            for r in kept.head(DRILLDOWN_ROWS).itertuples(index=False)
        ]
        suppressed[market] = len(dropped)
    federal_top = top[top["market"] == "federal"]
    fitted_in_federal = {
        name: int(federal_top.loc[federal_top["name"] == name, "n_jobs_tagged"].sum())
        for name in FEDERAL_FITTED
    }

    adm = frames["v_federal_skill_by_admission"]
    routes = []
    for route, group in sorted(adm.groupby("admission_route"), key=lambda kv: kv[0]):
        route_n = int(group["route_n_jobs"].max())
        hit = group[group["name"] == CIRCULARITY_SKILL]
        if len(hit):
            r = hit.iloc[0]
            rate = Rate(r["n_jobs_tagged"], route_n, pct=r["pct_of_jobs"], unit="jobs")
        else:  # never tagged on any federal job: zero, against the route's n
            rate = Rate(0, route_n, unit="jobs")
        routes.append((route, rate))

    return SkillDemand(
        basis=basis,
        categories=categories,
        composition=composition,
        flagged=flagged,
        drilldown=drilldown,
        suppressed=suppressed,
        routes=routes,
        fitted_in_federal=fitted_in_federal,
    )


# --------------------------------------------------------------------- #
# numbers for the narrative placeholders


def _share_of(data: SkillDemand, market: str, categories: list[str]) -> Rate:
    total = data.basis[market].n_tags
    return Rate(
        sum(data.composition[(market, c)].numerator for c in categories), total, unit="tags"
    )


def _top_categories(data: SkillDemand, market: str, k: int = 2) -> list[str]:
    ranked = sorted(data.categories, key=lambda c: (-data.composition[(market, c)].numerator, c))
    return [c for c in ranked if data.composition[(market, c)].numerator][:k]


def _gaps(data: SkillDemand) -> list[tuple[str, Gap]]:
    gaps = [
        (c, Gap(data.composition[("commercial", c)], data.composition[("federal", c)]))
        for c in data.categories
    ]
    gaps = [(c, g) for c, g in gaps if g.points is not None]
    return sorted(gaps, key=lambda cg: (-abs(cg[1].points), cg[0]))[:HEADLINE_GAPS]


def headline_numbers(data: SkillDemand) -> list[tuple[str, object]]:
    numbers: list[tuple[str, object]] = [
        (f"{m.capitalize()} jobs compared", Count(data.basis[m].n_jobs)) for m in MARKETS
    ]
    for market in MARKETS:
        top = _top_categories(data, market)
        for category in top:
            numbers.append(
                (
                    f"{market.capitalize()} share of tags in {category}",
                    data.composition[(market, category)],
                )
            )
        if len(top) == 2:
            numbers.append(
                (
                    f"{market.capitalize()} {top[0]} + {top[1]} combined",
                    _share_of(data, market, top),
                )
            )
    numbers += [(f"Largest gap: {c} (commercial − federal)", gap) for c, gap in _gaps(data)]
    return numbers


def meaning_numbers(data: SkillDemand) -> list[tuple[str, object]]:
    numbers: list[tuple[str, object]] = []
    for market in MARKETS:
        b = data.basis[market]
        numbers.append(
            (
                f"{market.capitalize()} tags per job",
                Ratio(b.n_tags, b.n_jobs, num_unit="tags", den_unit="jobs"),
            )
        )
        numbers.append(
            (f"{market.capitalize()} median description length, characters", b.text_length)
        )
    commercial = data.basis["commercial"]
    numbers.append(
        (
            f"Commercial jobs read at or near the ~500-character cap (≥ {NEAR_CAP_CHARS})",
            Rate(commercial.n_near_cap, commercial.n_jobs, unit="jobs"),
        )
    )
    federal = data.basis["federal"]
    numbers.append(
        ("Federal jobs read from full text", Rate(federal.n_full_text, federal.n_jobs, unit="jobs"))
    )
    numbers += [(f"{CIRCULARITY_SKILL}-tagged in {route}", rate) for route, rate in data.routes]
    fitted = sum(1 for n in data.fitted_in_federal.values() if n)
    numbers.append(
        (
            f"Federal-fitted taxonomy entries tagged on federal jobs (of {len(FEDERAL_FITTED)})",
            Count(fitted),
        )
    )
    return numbers


def action_numbers(data: SkillDemand) -> list[tuple[str, object]]:
    numbers: list[tuple[str, object]] = []
    for market in MARKETS:
        for row in data.drilldown[market][:ACTION_SKILLS]:
            numbers.append((f"{market.capitalize()}: {row.label}", row.rate))
        numbers.append(
            (
                f"{market.capitalize()} skills below the n ≥ {floor_for(market)} floor, not shown",
                Count(data.suppressed[market]),
            )
        )
    return numbers


# --------------------------------------------------------------------- #
# rendering


def render(data: SkillDemand, provenance: Provenance, out_dir: Path) -> Path:
    out = out_dir / SLUG
    out.mkdir(parents=True, exist_ok=True)
    doc = Doc(
        TITLE,
        provenance,
        SLUG,
        subtitle=(
            "Phase 5 report 1. Regenerates Phase 3 Investigation #2 "
            "(docs/phase_3_findings.md) from the SQL views."
        ),
    )

    doc.heading("Headline")
    doc.placeholder(
        "Headline",
        "One or two sentences on how the two markets' skill mix differs. "
        "Base it on the composition comparison (section 2), not the drill-down.",
        headline_numbers(data),
    )

    doc.heading("1. Who is compared")
    doc.paragraph(
        "**Commercial** is every Adzuna posting. **Federal** is every USAJobs posting "
        "classified in scope (`jobs.in_scope`). Skill tags are the taxonomy extractor's, "
        f"at confidence ≥ {SKILL_CONFIDENCE}. Each market is described on its own; nothing "
        "is pooled across them."
    )
    rows = []
    for market in MARKETS:
        b = data.basis[market]
        rows.append(
            [
                market,
                b.n_jobs,
                Rate(b.n_full_text, b.n_jobs, unit="jobs"),
                Rate(b.n_near_cap, b.n_jobs, unit="jobs"),
                b.text_length,
                Rate(b.n_jobs_tagged, b.n_jobs, unit="jobs"),
                b.n_tags,
                Ratio(b.n_tags, b.n_jobs, num_unit="tags", den_unit="jobs"),
            ]
        )
    doc.table(
        [
            "Market",
            "Jobs",
            "Read from full text",
            f"Read at/near the ~500-char cap (≥ {NEAR_CAP_CHARS})",
            "Description length, chars (median)",
            "Jobs with ≥ 1 tag",
            "Tags",
            "Tags per job",
        ],
        rows,
        caption="Text basis, from `v_skill_text_basis`.",
    )

    doc.heading("2. Skill-category composition (the primary comparison)")
    doc.paragraph(
        "Each market's skill tags, split by taxonomy category, as a share of **that "
        "market's own tags**. Federal descriptions are far longer than Adzuna's, so raw "
        "rates would mostly measure how much text each source has; shares compare what each "
        "market's text emphasizes. Read the margins as directional (see Methods and caveats)."
    )
    chart = grouped_barh(
        out / "composition.png",
        data.categories,
        {m: [data.composition[(m, c)] for c in data.categories] for m in MARKETS},
        title="Share of each market's skill tags, by category",
        xlabel=f"% of the market's own skill tags (confidence ≥ {SKILL_CONFIDENCE})",
        demo=provenance.is_demo,
        flagged=data.flagged,
    )
    doc.image(chart.name, "Grouped bars: share of each market's skill tags by category")
    doc.table(
        [
            "Category",
            "Commercial share of tags",
            "Federal share of tags",
            "Gap (commercial − federal)",
        ],
        [
            [
                category,
                data.composition[("commercial", category)],
                data.composition[("federal", category)],
                Gap(
                    data.composition[("commercial", category)],
                    data.composition[("federal", category)],
                    compact=True,
                ),
            ]
            for category in data.categories
        ],
        caption="From `v_skill_category_composition`; denominators from `v_skill_text_basis.n_tags`.",
    )
    flagged = sorted(data.flagged)
    if flagged:
        doc.paragraph(
            f"{FLAG_MARK} on the chart: a category with fewer tags than the market's drill-down "
            f"floor (commercial n ≥ {floor_for('commercial')}, federal n ≥ {floor_for('federal')}). "
            "Shown, but read it as directional. Here: "
            + ", ".join(f"{m} {c}" for m, c in flagged)
            + "."
        )

    doc.heading("3. Skill drill-down (directional texture)")
    doc.paragraph(
        "Individual skills, as a share of each market's jobs. This is texture, not the "
        "finding: it is never presented at the composition comparison's confidence, and it "
        "stays a table on purpose. Only skills at or above the reporting floor are shown. "
        f"{FITTED_MARK} marks taxonomy entries added while reading federal postings."
    )
    for market in MARKETS:
        floor = floor_for(market)
        doc.heading(f"{market.capitalize()} (n ≥ {floor})", level=3)
        shown = data.drilldown[market]
        header = "Share of jobs" + (f" ({TRUNCATION_LABEL})" if market == "commercial" else "")
        if shown:
            doc.table(
                ["Skill", "Category", header],
                [[r.label, r.category, r.rate] for r in shown],
                caption=f"From `v_skill_top_by_source`, top {DRILLDOWN_ROWS} at most.",
            )
        else:
            doc.paragraph(f"No {market} skill reaches the n ≥ {floor} floor.")
        if data.suppressed[market]:
            doc.paragraph(
                f"{data.suppressed[market]:,} more {market} skill(s) below n ≥ {floor} are not shown."
            )

    doc.heading("What it means")
    doc.placeholder(
        "What it means",
        "Why the mixes differ, and how far the measurement itself can explain it "
        "(text basis, truncation, taxonomy provenance, the Statistics check).",
        meaning_numbers(data),
    )
    doc.heading("What to do about it")
    doc.placeholder(
        "What to do about it",
        "What a job seeker (or this project) should do with the contrast. Keep skill-level "
        "advice at drill-down confidence.",
        action_numbers(data),
    )

    _methods(doc, data)
    path = out / "report.md"
    path.write_text(doc.render())
    return path


def _methods(doc: Doc, data: SkillDemand) -> None:
    commercial, federal = data.basis["commercial"], data.basis["federal"]
    doc.heading("Methods and caveats")
    doc.bullets(
        [
            ("Commercial jobs (every Adzuna posting)", Count(commercial.n_jobs)),
            (
                "Federal jobs (USAJobs postings classified in scope)",
                Count(federal.n_jobs),
            ),
            *[
                (f"Federal jobs admitted via `{route}`", Count(rate.denominator))
                for route, rate in data.routes
            ],
            f"Skill tags: the curated-taxonomy extractor (`src/cleaning/skill_extractor.py`) over "
            f"the title plus the full description (federal) or Adzuna's description "
            f"(commercial), at confidence ≥ {SKILL_CONFIDENCE} in every view used.",
            "Composition, not magnitude: shares of each market's own tags, because the two "
            "sources carry very different amounts of text (median description length below).",
            ("Commercial median description length, characters", commercial.text_length),
            ("Federal median description length, characters", federal.text_length),
        ]
    )
    doc.heading("Truncation cuts both ways", level=3)
    doc.bullets(
        [
            (
                f"Commercial jobs read at or near Adzuna's ~500-character cap (≥ {NEAR_CAP_CHARS} chars)",
                Rate(commercial.n_near_cap, commercial.n_jobs, unit="jobs"),
            ),
            (
                "Federal jobs read from full announcement text",
                Rate(federal.n_full_text, federal.n_jobs, unit="jobs"),
            ),
            f"Commercial skill rates are **{TRUNCATION_LABEL}**: a skill cut off by the cap is "
            "missing, so a low commercial rate or rank may be an artifact, not low demand.",
            "Commercial's composition isn't a neutral baseline either: the first ~500 characters "
            "of a posting may favour workflow and BI tools and push languages and ML/statistics "
            "later, past the cap. That mechanism is measured on the federal side only. Treat the "
            "margins as a floor on the true contrast, not the contrast itself "
            "(docs/findings_commercial_vs_federal_skills.md).",
        ]
    )
    doc.heading("Taxonomy provenance", level=3)
    doc.paragraph(
        f"These entries were added while reading federal postings, so the federal side reflects "
        f"an instrument partly built from federal text ({FITTED_MARK} in the drill-down):"
    )
    doc.table(
        ["Entry", "Change", "Federal jobs tagged in this data"],
        [
            [name, change, data.fitted_in_federal.get(name, 0)]
            for name, change in FEDERAL_FITTED.items()
        ],
    )
    doc.heading(f"{CIRCULARITY_SKILL}-tag check", level=3)
    doc.paragraph(
        f"Is the federal ml_stats share just the occupational-series label echoed back? If the "
        f"{CIRCULARITY_SKILL} tag rate holds in a route admitted by series code without a "
        f"statistics label (Operations Research), it isn't. From `v_federal_skill_by_admission`."
    )
    if data.routes:
        doc.table(
            ["Admission route", f"{CIRCULARITY_SKILL}-tagged jobs", "Note"],
            [
                [
                    f"`{route}`",
                    rate,
                    f"below the federal n ≥ {floor_for('federal')} floor: directional"
                    if below_floor(rate.denominator, "federal")
                    else "",
                ]
                for route, rate in data.routes
            ],
        )
    else:
        doc.paragraph("No federal in-scope jobs in this data.")
    doc.heading("Reporting floors and pooling", level=3)
    doc.bullets(
        [
            f"Skill drill-down floors: commercial n ≥ {floor_for('commercial')}, federal "
            f"n ≥ {floor_for('federal')} (docs/phase_3_findings.md). Rows below are not shown; "
            "composition categories below are shown and marked.",
            ("Commercial drill-down rows suppressed", Count(data.suppressed["commercial"])),
            ("Federal drill-down rows suppressed", Count(data.suppressed["federal"])),
            "Every number is per market; nothing is pooled across commercial and federal.",
            "Sources: `sql/views/v_skill_category_composition.sql`, `v_skill_text_basis.sql`, "
            "`v_skill_top_by_source.sql`, `v_federal_skill_by_admission.sql`; "
            "docs/phase_3_findings.md (Investigation #2); "
            "docs/findings_commercial_vs_federal_skills.md.",
        ]
    )
