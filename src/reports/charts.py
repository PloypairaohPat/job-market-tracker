"""Matplotlib PNG charts that follow the same guardrails as the tables.

Every bar is a Rate and is labelled with its full rendering (percentage,
count and denominator), so a chart lifted out of the report still carries
its n. Commercial skill rates need "truncation-floored" in the title or axis
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

from src.reports.guardrails import TRUNCATION_LABEL, GuardrailError, Rate  # noqa: E402
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
