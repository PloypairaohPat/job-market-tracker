"""Report 4: What commercial data-analyst postings pay (Phase 3 Investigation #1).

The commercial (Adzuna) salary picture, rebuilt with the report kit: who has a
usable salary, the employer-disclosed anchor, Adzuna's predicted salaries as a
labelled comparison only, disclosed salaries by seniority and by metro, and why
there are no skill premiums here. Narrative sections are [TO WRITE]
placeholders with this run's numbers; the kit writes no conclusions.

Views read:
  v_commercial_salary_clean  one row per clean commercial posting (salary_quality
                             'ok', USD, year): its midpoint, basis, seniority,
                             metro. Read for the medians only: no job id, title
                             or per-posting row ever reaches the output
  v_salary_population        every commercial posting by quality, currency,
                             period and basis: who is measured, and exclusions
  v_salary_skill_coverage    how thinly each basis carries skill tags
  v_ingestion_daily          snapshot days so far (no trend is computed)

Guardrails (src/reports/guardrails.py):
  - disclosed and predicted are never pooled: every summary is one basis, and
    the comparison is a SalaryDiff of two summaries
  - median and IQR only; the text never says "mean" or "average" outside the
    one Methods sentence on why (check_salary_wording)
  - SALARY_FLOOR (n >= 15): a group under it shows its n, never a median
  - the headline's only salary figure is the employer-disclosed median
  - seniority NULL is "no title signal", never folded into mid; metro NULL is
    "not on the tracked metro list"
  - federal is excluded: GS bands aren't comparable, and federal pay is
    disclosed by law
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.reports.charts import salary_boxes
from src.reports.guardrails import (
    MEDIAN_RATIONALE,
    SALARY_FLOOR,
    TRUNCATION_LABEL,
    Count,
    FlooredSalary,
    Rate,
    SalaryDiff,
    SalarySummary,
    check_salary_wording,
    skill_rate,
    summarize_salary,
)
from src.reports.markdown import Doc
from src.reports.provenance import Provenance

SLUG = "what-postings-pay"
TITLE = "What commercial data-analyst postings pay"
CLEAN_VIEW = "v_commercial_salary_clean"
VIEWS = (CLEAN_VIEW, "v_salary_population", "v_salary_skill_coverage", "v_ingestion_daily")
DISCLOSED, PREDICTED = "employer-disclosed", "Adzuna-predicted"
SENIORITY_ORDER = ("junior", "mid", "senior", "lead")
NO_TITLE_SIGNAL = "no title signal"
NOT_ON_METRO_LIST = "not on the tracked metro list"
NO_DATA = "no data"
PREMIUM_DOC = "docs/findings_skill_premium_deferred.md"


@dataclass(frozen=True)
class Population:
    n_commercial: int = 0
    with_salary: Rate = Rate(0, 0, unit="postings")
    disclosed_any: Rate = Rate(0, 0, unit="postings")
    exclusions: tuple[tuple[str, Rate], ...] = ()
    clean: Rate = Rate(0, 0, unit="postings")
    clean_by_basis: tuple[tuple[str, Rate], ...] = ()


@dataclass(frozen=True)
class SkillCoverage:
    basis: str
    n_jobs: int
    tagged: Rate
    largest_skill_n: int
    n_skills_at_floor: int


@dataclass
class SalaryReport:
    population: Population
    disclosed: SalarySummary
    predicted: SalarySummary
    by_seniority: list[SalarySummary]
    by_metro: list[SalarySummary]
    skills: list[SkillCoverage]
    snapshot_days: int
    first_day: str | None
    last_day: str | None
    # the values behind each box (never rendered as rows)
    values: dict[str, list[float]] = field(default_factory=dict)

    @property
    def diff(self) -> SalaryDiff | None:
        if min(self.disclosed.n, self.predicted.n) < SALARY_FLOOR:
            return None
        return SalaryDiff(self.predicted, self.disclosed)


# --------------------------------------------------------------------- #
# compute


def _exclusion_reason(r) -> str:
    if pd.isna(r.salary_quality):
        return "no salary figure"
    if r.salary_quality != "ok":
        return f"salary_quality '{r.salary_quality}'"
    if r.salary_currency != "USD":
        return "salary not in USD"
    return f"pay period '{r.salary_period}', not a year"


def _population(frame: pd.DataFrame) -> Population:
    if frame.empty:
        return Population()
    total = int(frame["market_n_postings"].iloc[0])
    has_salary = frame["salary_quality"].notna()
    disclosed = has_salary & (frame["salary_is_predicted"] == False)  # noqa: E712 (NULL stays out)
    clean = frame[frame["in_clean_population"]]
    n_clean = int(clean["n"].sum())
    reasons: dict[str, int] = {}
    for r in frame[~frame["in_clean_population"]].itertuples(index=False):
        reason = _exclusion_reason(r)
        reasons[reason] = reasons.get(reason, 0) + int(r.n)
    by_basis = [
        (DISCLOSED, int(clean.loc[clean["salary_is_predicted"] == False, "n"].sum())),  # noqa: E712
        (PREDICTED, int(clean.loc[clean["salary_is_predicted"] == True, "n"].sum())),  # noqa: E712
    ]
    unknown = n_clean - sum(n for _, n in by_basis)
    if unknown:
        by_basis.append(("basis unknown (salary_is_predicted NULL): in neither", unknown))
    return Population(
        n_commercial=total,
        with_salary=Rate(int(frame.loc[has_salary, "n"].sum()), total, unit="postings"),
        disclosed_any=Rate(int(frame.loc[disclosed, "n"].sum()), total, unit="postings"),
        exclusions=tuple(
            (reason, Rate(n, total, unit="postings"))
            for reason, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        clean=Rate(n_clean, total, unit="postings"),
        clean_by_basis=tuple(
            (basis, Rate(n, n_clean, unit="clean postings")) for basis, n in by_basis
        ),
    )


def _groups(disclosed: pd.DataFrame, column: str, null_label: str) -> list[SalarySummary]:
    """One summary per value of `column` (NULL as its own, last, labelled group)."""
    known = [v for v in disclosed[column].dropna().unique()]
    if column == "seniority":
        known.sort(key=lambda v: (SENIORITY_ORDER.index(v) if v in SENIORITY_ORDER else 99, v))
    else:
        counts = disclosed[column].value_counts()
        known.sort(key=lambda v: (-counts[v], v))
    out = [
        summarize_salary(disclosed[disclosed[column] == v], DISCLOSED, CLEAN_VIEW, group=str(v))
        for v in known
    ]
    if disclosed[column].isna().any():
        out.append(
            summarize_salary(
                disclosed[disclosed[column].isna()], DISCLOSED, CLEAN_VIEW, group=null_label
            )
        )
    return out


def compute(frames: dict[str, pd.DataFrame]) -> SalaryReport:
    clean = frames[CLEAN_VIEW]
    known_basis = clean[clean["salary_is_predicted"].notna()]  # NULL basis: counted, not summarized
    disclosed_rows = known_basis[known_basis["salary_is_predicted"] == False]  # noqa: E712
    disclosed = summarize_salary(known_basis, DISCLOSED, CLEAN_VIEW)
    predicted = summarize_salary(known_basis, PREDICTED, CLEAN_VIEW)
    by_seniority = _groups(disclosed_rows, "seniority", NO_TITLE_SIGNAL)
    by_metro = _groups(disclosed_rows, "metro_area", NOT_ON_METRO_LIST)

    def values(rows: pd.DataFrame) -> list[float]:
        return rows["salary_midpoint"].dropna().astype(float).tolist()

    box_values = {
        DISCLOSED: values(disclosed_rows),
        PREDICTED: values(known_basis[known_basis["salary_is_predicted"] == True]),  # noqa: E712
    }
    for s in by_seniority:
        rows = (
            disclosed_rows[disclosed_rows["seniority"].isna()]
            if s.group == NO_TITLE_SIGNAL
            else disclosed_rows[disclosed_rows["seniority"] == s.group]
        )
        box_values[f"seniority:{s.group}"] = values(rows)

    skills = [
        SkillCoverage(
            basis=r.basis,
            n_jobs=int(r.n_jobs),
            tagged=skill_rate(int(r.n_jobs_tagged), int(r.n_jobs), "commercial"),
            largest_skill_n=int(r.largest_skill_n),
            n_skills_at_floor=int(r.n_skills_at_floor),
        )
        for r in frames["v_salary_skill_coverage"].itertuples(index=False)
    ]
    daily = frames["v_ingestion_daily"]
    adzuna_days = daily.loc[daily["source"] == "adzuna", "snapshot_date"] if len(daily) else []
    days = sorted(pd.Series(adzuna_days).dropna().unique())
    return SalaryReport(
        population=_population(frames["v_salary_population"]),
        disclosed=disclosed,
        predicted=predicted,
        by_seniority=by_seniority,
        by_metro=by_metro,
        skills=skills,
        snapshot_days=len(days),
        first_day=str(pd.Timestamp(days[0]).date()) if days else None,
        last_day=str(pd.Timestamp(days[-1]).date()) if days else None,
        values=box_values,
    )


# --------------------------------------------------------------------- #
# numbers for the narrative placeholders


def _cleared(groups: list[SalarySummary]) -> list[SalarySummary]:
    return [g for g in groups if g.n >= SALARY_FLOOR]


def headline_numbers(data: SalaryReport) -> list[tuple[str, object]]:
    # the employer-disclosed median is the ONLY salary figure in the headline
    return [
        ("Employer-disclosed salary midpoint", FlooredSalary(data.disclosed)),
        ("Commercial postings with an employer-disclosed salary", data.population.disclosed_any),
        ("Commercial postings in the clean salary population", data.population.clean),
    ]


def meaning_numbers(data: SalaryReport) -> list[tuple[str, object]]:
    numbers: list[tuple[str, object]] = [
        (
            "Adzuna-predicted salary midpoint (a model estimate, for comparison)",
            FlooredSalary(data.predicted),
        ),
        (
            "Adzuna-predicted minus employer-disclosed",
            data.diff or _no_diff(data.predicted, data.disclosed),
        ),
        ("Commercial postings with a salary figure of any kind", data.population.with_salary),
    ]
    numbers += [
        (f"Employer-disclosed, seniority {g.group}", FlooredSalary(g))
        for g in _cleared(data.by_seniority)
    ]
    numbers += [
        (f"{s.basis}: postings with any skill tag ({TRUNCATION_LABEL})", s.tagged)
        for s in data.skills
    ]
    return numbers


def action_numbers(data: SalaryReport) -> list[tuple[str, object]]:
    return [
        *[
            (f"Employer-disclosed, metro {g.group}", FlooredSalary(g))
            for g in _cleared(data.by_metro)
        ],
        ("Metros clearing the n ≥ 15 floor", Count(len(_cleared(data.by_metro)))),
        ("Distinct snapshot days so far", Count(data.snapshot_days)),
    ]


def _no_diff(a: SalarySummary, b: SalarySummary) -> str:
    short = [s.basis for s in (a, b) if s.n < SALARY_FLOOR]
    return f"not shown: {' and '.join(short)} under the n ≥ {SALARY_FLOOR} floor"


# --------------------------------------------------------------------- #
# rendering


def render(data: SalaryReport, provenance: Provenance, out_dir: Path) -> Path:
    out = out_dir / SLUG
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()  # a chart not drawn this run mustn't linger from the last
    doc = Doc(
        TITLE,
        provenance,
        SLUG,
        subtitle=(
            "Phase 5 report 4, regenerating Phase 3 Investigation #1. What commercial (Adzuna) "
            "data-analyst postings pay, from employer-disclosed salaries, with Adzuna's predicted "
            "salaries only as a labelled comparison."
        ),
    )

    doc.heading("Headline")
    doc.placeholder(
        "Headline",
        "One or two sentences on what employer-disclosed commercial postings pay. The "
        "employer-disclosed median is the only salary figure to quote here.",
        headline_numbers(data),
    )

    _who_is_measured(doc, data)
    _anchor(doc, data)
    _comparison(doc, data, out, provenance.is_demo)
    _seniority(doc, data, out, provenance.is_demo)
    _metro(doc, data)
    _skills(doc, data)
    _over_time(doc, data)

    doc.heading("What it means")
    doc.placeholder(
        "What it means",
        "What the disclosed figure says about analyst pay, how far predicted salaries differ, "
        "and what the measurement can't show (who discloses, title-only seniority, the metro list).",
        meaning_numbers(data),
    )
    doc.heading("What to do about it")
    doc.placeholder(
        "What to do about it",
        "What a job seeker should take from this, at aggregate level: a range to expect, never a "
        "promise about one posting.",
        action_numbers(data),
    )

    _methods(doc, data)
    text = doc.render()
    check_salary_wording(text)
    path = out / "report.md"
    path.write_text(text)
    return path


def _who_is_measured(doc: Doc, data: SalaryReport) -> None:
    p = data.population
    doc.heading("1. Who is measured")
    if not p.n_commercial:
        doc.paragraph(f"**{NO_DATA}:** no commercial postings in this database.")
        return
    doc.paragraph(
        "Every commercial (Adzuna) posting, narrowed to the clean salary population "
        "(`salary_quality = 'ok'`, USD, a yearly figure). Adzuna returns a salary for nearly every "
        "posting because its model fills in the ones employers didn't disclose, so **\"salary "
        'present" is API behaviour, not a market fact**. The employer-disclosed share is the '
        "market fact."
    )
    rows = [
        ["All commercial postings", Count(p.n_commercial)],
        ["With a salary figure of any kind (API behaviour)", p.with_salary],
        ["With an employer-disclosed salary figure (the market fact)", p.disclosed_any],
        *[[f"Excluded: {reason}", rate] for reason, rate in p.exclusions],
        ["Clean salary population", p.clean],
        *[[f"Clean: {basis}", rate] for basis, rate in p.clean_by_basis],
    ]
    doc.table(
        ["Population", "Postings"],
        rows,
        caption="From `v_salary_population`. Exclusions and the clean total are shares of every "
        "commercial posting; the clean split is a share of the clean population.",
    )


def _anchor(doc: Doc, data: SalaryReport) -> None:
    doc.heading("2. The disclosed anchor")
    doc.paragraph(
        "The salary midpoint employers disclosed themselves: the only salary figure in the "
        "headline."
    )
    doc.bullets([("Employer-disclosed salary midpoint", FlooredSalary(data.disclosed))])


def _comparison(doc: Doc, data: SalaryReport, out: Path, demo: bool) -> None:
    doc.heading("3. Predicted vs disclosed, as a comparison")
    doc.paragraph(
        "Adzuna's predicted salaries are **its own model's estimate, not a market observation**. "
        "They are summarized separately and compared with the disclosed figure; the two are "
        "never pooled into one number."
    )
    doc.table(
        ["Basis", "Salary midpoint"],
        [[DISCLOSED, FlooredSalary(data.disclosed)], [PREDICTED, FlooredSalary(data.predicted)]],
        caption="From `v_commercial_salary_clean`, one basis per row.",
    )
    doc.bullets(
        [
            (
                "Adzuna-predicted minus employer-disclosed",
                data.diff or _no_diff(data.predicted, data.disclosed),
            )
        ]
    )
    boxes = [
        (s, data.values[s.basis]) for s in (data.disclosed, data.predicted) if s.n >= SALARY_FLOOR
    ]
    if len(boxes) == 2:
        chart = salary_boxes(
            out / "disclosed-vs-predicted.png",
            boxes,
            title="Employer-disclosed and Adzuna-predicted salaries, drawn separately",
            demo=demo,
        )
        doc.image(chart.name, "Two boxes: employer-disclosed and Adzuna-predicted salary midpoints")
    else:
        doc.paragraph(f"No chart: both bases need n ≥ {SALARY_FLOOR} to be drawn side by side.")


def _group_table(doc: Doc, groups: list[SalarySummary], header: str, n_disclosed: int) -> None:
    doc.table(
        [header, "Postings (share of disclosed)", "Salary midpoint"],
        [[g.group, Rate(g.n, n_disclosed, unit="postings"), FlooredSalary(g)] for g in groups],
        caption=f"Employer-disclosed postings only. A group under n ≥ {SALARY_FLOOR} shows its n; "
        "its median is withheld.",
    )


def _seniority(doc: Doc, data: SalaryReport, out: Path, demo: bool) -> None:
    doc.heading("4. Disclosed by seniority")
    if not data.disclosed.n:
        doc.paragraph(f"**{NO_DATA}:** no employer-disclosed postings in the clean population.")
        return
    doc.paragraph(
        "Seniority comes from the **job title only** (`src/cleaning/seniority.py`), so it is "
        f"instrument-limited: a level stated only in the description is invisible. "
        f"**{NO_TITLE_SIGNAL.capitalize()}** is its own row, never folded into mid."
    )
    _group_table(doc, data.by_seniority, "Seniority", data.disclosed.n)
    cleared = _cleared(data.by_seniority)
    if cleared:
        chart = salary_boxes(
            out / "disclosed-by-seniority.png",
            [(g, data.values[f"seniority:{g.group}"]) for g in cleared],
            title=f"Employer-disclosed salaries by seniority (groups with n ≥ {SALARY_FLOOR})",
            demo=demo,
        )
        doc.image(chart.name, "Boxes: employer-disclosed salary midpoints by seniority")
    else:
        doc.paragraph(f"No chart: no seniority group reaches n ≥ {SALARY_FLOOR}.")


def _metro(doc: Doc, data: SalaryReport) -> None:
    doc.heading("5. Disclosed by metro")
    if not data.disclosed.n:
        doc.paragraph(f"**{NO_DATA}:** no employer-disclosed postings in the clean population.")
        return
    doc.paragraph(
        "Metro is a lookup against a curated list of tracked metros (8 cities plus DC, "
        "`src/cleaning/metro.py`), never a default. A posting anywhere else, or with an unparsed "
        f"location, is **{NOT_ON_METRO_LIST}**: that row describes the list, not a market."
    )
    _group_table(doc, data.by_metro, "Metro", data.disclosed.n)


def _skills(doc: Doc, data: SalaryReport) -> None:
    doc.heading("6. Why there are no skill premiums here")
    doc.table(
        [
            "Basis",
            "Clean postings",
            f"With any skill tag ({TRUNCATION_LABEL})",
            "Largest single-skill n",
            f"Skills at n ≥ {SALARY_FLOOR}",
        ],
        [
            [s.basis, s.n_jobs, s.tagged, s.largest_skill_n, s.n_skills_at_floor]
            for s in data.skills
        ],
        caption="From `v_salary_skill_coverage` (tags at confidence ≥ 0.8).",
    )
    disclosed = next((s for s in data.skills if s.basis == DISCLOSED), None)
    reached = disclosed.n_skills_at_floor if disclosed is not None else 0
    tags = (
        f"**Disclosed tags:** on this data {reached:,} skill(s) reach n ≥ {SALARY_FLOOR} among "
        "employer-disclosed postings, so this reason doesn't hold here; the other two still do, "
        "and no premium is computed."
        if reached
        else "**Too few disclosed postings carry tags:** no skill reaches n ≥ "
        f"{SALARY_FLOOR} among employer-disclosed postings, the only basis a premium could use."
    )
    doc.paragraph("A skill premium isn't computed. The three reasons, checked against this data:")
    doc.bullets(
        [
            tags,
            "**The text is truncation-floored:** Adzuna cuts descriptions at about 500 characters, "
            "so tags undercount, and unevenly.",
            "**Pooling predicted salaries would make any premium partly Adzuna's own model,** not "
            "what employers pay.",
        ]
    )
    doc.paragraph(f"What would unblock it: [{PREMIUM_DOC}](../../{PREMIUM_DOC}).")


def _over_time(doc: Doc, data: SalaryReport) -> None:
    doc.heading("7. Over time")
    span = f" ({data.first_day} to {data.last_day})" if data.snapshot_days else ""
    doc.bullets([("Distinct commercial snapshot days so far" + span, Count(data.snapshot_days))])
    doc.paragraph(
        "Salary trends wait for history: this report computes no trend, and every figure above "
        "covers all the postings seen so far."
    )


def _methods(doc: Doc, data: SalaryReport) -> None:
    doc.heading("Methods and caveats")
    doc.bullets(
        [
            "Population: commercial (Adzuna) postings with `salary_quality = 'ok'`, "
            "`salary_currency = 'USD'` and `salary_period = 'year'` (`v_commercial_salary_clean`).",
            "Each posting's salary is its midpoint, (salary_min + salary_max) / 2.",
            MEDIAN_RATIONALE,
            "IQR: the 25th to 75th percentile, linear interpolation (as Postgres's percentile_cont).",
            "Predicted vs disclosed: `salary_is_predicted` separates Adzuna's model estimates from "
            "employer-disclosed figures. They are summarized separately and never pooled.",
            f"Floor: a group under n ≥ {SALARY_FLOOR} shows its n, but its median is withheld.",
            "Seniority comes from the title only; metro from a curated list of tracked metros; "
            "Adzuna's text is truncated at about 500 characters.",
            "Federal postings are excluded: GS pay bands aren't comparable with commercial "
            "salaries, and federal pay is disclosed by law, so there is no disclosure selection "
            "to compare.",
            "Who discloses: Phase 3 found that employer-disclosed salaries skew toward "
            "compensation-forward posting text and disclosure-law metros, which partially "
            "explains why they differ from predicted ones; a residual is unexplained. That is "
            "a hypothesis, not a proven cause.",
            ("Commercial postings read", Count(data.population.n_commercial)),
        ]
    )
