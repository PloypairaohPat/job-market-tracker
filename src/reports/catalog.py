"""The reports, by slug, and the one function that generates any of them.

A report module exposes SLUG, TITLE, VIEWS, compute(frames) and
render(data, provenance, out_dir). `generate` reads exactly its VIEWS
through a ViewReader, stamps provenance from what was read, and renders.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

from src.reports import disclosure, employers, skill_demand
from src.reports.provenance import Provenance
from src.reports.views import ViewReader

REPORTS: dict[str, ModuleType] = {m.SLUG: m for m in (skill_demand, disclosure, employers)}


def generate(slug: str, reader: ViewReader, out_dir: Path) -> Path:
    module = REPORTS[slug]
    frames = {view: reader.read(view) for view in module.VIEWS}
    data = module.compute(frames)
    provenance = Provenance.collect(reader.database_name(), reader.rows_read)
    return module.render(data, provenance, out_dir)
