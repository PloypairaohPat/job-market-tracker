"""The only way a report reads the database: whole SQL views, by name.

`ViewReader.read("v_x")` runs `SELECT * FROM v_x` and nothing else. The name
must be a `v_*` view defined in sql/views/, so a report can't query a base
table or hand-write SQL: if a number isn't in a view, add a view (with tests)
rather than computing it from tables here. Filtering and arithmetic on what a
view returns happen in pandas, through src/reports/guardrails.py.

The reader records each view it read and its row count, for the report's
provenance stamp.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError

from src.reports.guardrails import GuardrailError

VIEWS_DIR = Path(__file__).resolve().parents[2] / "sql" / "views"
_VIEW_NAME = re.compile(r"^v_[a-z0-9_]+$")


def repo_views(views_dir: Path = VIEWS_DIR) -> frozenset[str]:
    """Names of the views defined in sql/views/ (file stem = view name)."""
    return frozenset(p.stem for p in views_dir.glob("v_*.sql"))


class ViewReader:
    def __init__(self, engine: Engine, views_dir: Path = VIEWS_DIR) -> None:
        self.engine = engine
        self.known = repo_views(views_dir)
        self.rows_read: dict[str, int] = {}

    def read(self, view: str) -> pd.DataFrame:
        if not _VIEW_NAME.match(view) or view not in self.known:
            raise GuardrailError(
                f"{view!r} is not a view in sql/views/: reports read only from the views"
            )
        try:
            with self.engine.connect() as conn:
                frame = pd.read_sql(text(f'SELECT * FROM "{view}"'), conn)
        except (ProgrammingError, pd.errors.DatabaseError) as exc:
            # pandas wraps the driver error in its own DatabaseError
            raise GuardrailError(
                f"view {view} can't be read from the database ({exc}). Run `make views` first."
            ) from exc
        self.rows_read[view] = len(frame)
        return frame

    def database_name(self) -> str:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT current_database()")).scalar_one()
