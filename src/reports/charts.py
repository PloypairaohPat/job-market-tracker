"""Matplotlib PNG charts that follow the same guardrails as the tables.

Every bar is a Rate and is labelled with its full rendering (percentage,
count and denominator), so a chart lifted out of the report still carries
its n. Every salary box is ONE SalarySummary's values, labelled with its
group, basis and n, and only at or above SALARY_FLOOR: there is no way to
draw a pooled box. Commercial skill rates need "truncation-floored" in the title or axis
label, and a demo/test database puts the demo banner in the title.

Colours are slots 1 and 2 of the dataviz reference palette (light mode),
validated for colour-vision deficiency; identity is never colour alone (a
legend plus direct labels). Output is deterministic: fixed size and DPI, no
software metadata in the PNG.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (backend must be set first)
import numpy as np  # noqa: E402
from matplotlib import cbook  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from src.reports.guardrails import (  # noqa: E402
    SALARY_FLOOR,
    TRUNCATION_LABEL,
    GuardrailError,
    Rate,
    SalarySummary,
)
from src.reports.provenance import DEMO_BANNER  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e4e3df"
SERIES_COLORS = ("#2a78d6", "#eb6834")  # blue, orange: validated pair
FLAG_MARK = "‡"


def grouped_barh(
    path: Path,
    categories: list[str],
    series: dict[str, list[Rate]],
    *,
    title: str,
    xlabel: str,
    demo: bool,
    flagged: frozenset[tuple[str, str]] = frozenset(),
) -> Path:
    """One horizontal bar per (category, series), labelled with its Rate.

    `flagged` holds (series, category) pairs to mark with FLAG_MARK (groups
    below a reporting floor: shown, but marked directional).
    """
    if not 1 <= len(series) <= len(SERIES_COLORS):
        raise GuardrailError(f"grouped_barh takes 1-{len(SERIES_COLORS)} series")
    for name, rates in series.items():
        if len(rates) != len(categories):
            raise GuardrailError(f"series {name!r} has {len(rates)} values for {len(categories)}")
        if not all(isinstance(r, Rate) for r in rates):
            raise GuardrailError("chart values must be Rates, so each bar shows its denominator")
    floored = any(r.truncation_floored for rates in series.values() for r in rates)
    if floored and TRUNCATION_LABEL not in f"{title} {xlabel}":
        raise GuardrailError(f"chart shows commercial skill rates without {TRUNCATION_LABEL!r}")

    n_series = len(series)
    bar = 0.34 if n_series == 2 else 0.5
    gap = 0.03
    fig, ax = plt.subplots(figsize=(9, 1.4 + 0.62 * len(categories)), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    peak = max((r.value or 0.0 for rates in series.values() for r in rates), default=0.0)
    for i, (name, rates) in enumerate(series.items()):
        offset = (i - (n_series - 1) / 2) * (bar + gap)
        ys = [k + offset for k in range(len(categories))]
        values = [r.value or 0.0 for r in rates]
        ax.barh(ys, values, height=bar, color=SERIES_COLORS[i], label=name, zorder=2)
        for y, rate, category in zip(ys, rates, categories, strict=True):
            mark = f" {FLAG_MARK}" if (name, category) in flagged else ""
            ax.text(
                (rate.value or 0.0) + peak * 0.01,
                y,
                rate.render() + mark,
                va="center",
                ha="left",
                fontsize=7.5,
                color=INK,
            )

    ax.set_yticks(range(len(categories)), categories, color=INK, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, max(peak, 1.0) * 1.55)
    ax.set_xlabel(xlabel, color=INK_SECONDARY, fontsize=8.5)
    ax.set_xticks([t for t in ax.get_xticks() if 0 <= t <= 100])  # percentages: no tick past 100
    ax.tick_params(axis="x", colors=INK_SECONDARY, labelsize=8)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    full_title = f"{DEMO_BANNER}\n{title}" if demo else title
    ax.set_title(full_title, loc="left", color=INK, fontsize=10.5, pad=12)
    if n_series > 1:
        # above the plot, right-aligned: clear of every bar label
        ax.legend(
            frameon=False,
            fontsize=8.5,
            loc="lower right",
            bbox_to_anchor=(1.0, 1.0),
            ncol=n_series,
            labelcolor=INK,
        )
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)
    return path


def salary_boxes(
    path: Path,
    boxes: list[tuple[SalarySummary, list[float]]],
    *,
    title: str,
    demo: bool,
    xlabel: str = "Annual salary midpoint (USD)",
) -> Path:
    """One horizontal box per SalarySummary: median line, IQR box, whiskers at
    1.5 IQR, no outlier points (no single posting is drawn). Each box is
    labelled with its group or basis and its n, and annotated with its median
    and IQR. A box under SALARY_FLOOR, or whose values don't reproduce its
    summary's median, is refused."""
    if not 1 <= len(boxes) <= 8:
        raise GuardrailError("salary_boxes takes 1-8 boxes")
    stats = []
    for summary, values in boxes:
        if not isinstance(summary, SalarySummary):
            raise GuardrailError("each salary box is one SalarySummary: never a pooled box")
        if summary.n < SALARY_FLOOR or len(values) != summary.n:
            raise GuardrailError(
                f"{summary.label}: a box needs n ≥ {SALARY_FLOOR} and exactly its summary's values"
            )
        if abs(float(np.median(values)) - summary.median) > 0.5:
            raise GuardrailError(f"{summary.label}: the box's values don't match its summary")
        (stat,) = cbook.boxplot_stats(np.asarray(values, dtype=float), whis=1.5)
        stat["label"] = f"{summary.group or summary.basis}\n(n={summary.n:,})"
        stats.append(stat)

    fig, ax = plt.subplots(figsize=(9, 1.5 + 0.8 * len(boxes)), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    bases = list(dict.fromkeys(summary.basis for summary, _ in boxes))
    if len(bases) > len(SERIES_COLORS):
        raise GuardrailError(f"salary_boxes colours at most {len(SERIES_COLORS)} bases")
    artists = ax.bxp(
        stats,
        orientation="horizontal",
        showfliers=False,
        patch_artist=True,
        widths=0.5,
        medianprops={"color": INK, "linewidth": 1.6},
        whiskerprops={"color": INK_SECONDARY},
        capprops={"color": INK_SECONDARY},
        boxprops={"edgecolor": INK_SECONDARY},
    )
    for patch, (summary, _) in zip(artists["boxes"], boxes, strict=True):
        patch.set_facecolor(SERIES_COLORS[bases.index(summary.basis)])
        patch.set_alpha(0.55)
    span = max(s["whishi"] for s in stats) - min(s["whislo"] for s in stats) or 1.0
    for y, (stat, (summary, _)) in enumerate(zip(stats, boxes, strict=True), start=1):
        ax.text(
            stat["whishi"] + span * 0.02,
            y,
            f"median ${summary.median:,.0f}; IQR ${summary.p25:,.0f}–${summary.p75:,.0f}"
            f" ({summary.basis})",
            va="center",
            ha="left",
            fontsize=7.5,
            color=INK,
        )
    ax.invert_yaxis()
    low, high = min(s["whislo"] for s in stats), max(s["whishi"] for s in stats)
    ax.set_xlim(low - span * 0.05, high + span * 0.85)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v / 1000:,.0f}k"))
    ax.set_xlabel(xlabel, color=INK_SECONDARY, fontsize=8.5)
    ax.tick_params(axis="x", colors=INK_SECONDARY, labelsize=8)
    ax.tick_params(axis="y", length=0, labelsize=9, labelcolor=INK)
    ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    full_title = f"{DEMO_BANNER}\n{title}" if demo else title
    ax.set_title(full_title, loc="left", color=INK, fontsize=10.5, pad=12)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)
    return path
