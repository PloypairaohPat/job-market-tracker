"""Apply every sql/views/*.sql file to the database, in file-name order.

Run:  python scripts/apply_views.py      (or: make views)

Each file is a single `CREATE OR REPLACE VIEW`, so re-running is safe.
All files are applied in ONE transaction: if any view fails, none of
them change. File-name order is the dependency order -- a view that
reads another view must sort after it (v_employer_sponsorship before
v_job_visa_outlook).

Goes through SQLAlchemy against DATABASE_URL, so the
postgresql+psycopg2:// URL form works (psql doesn't understand it).
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

VIEWS_DIR = Path(__file__).resolve().parents[1] / "sql" / "views"


def view_files(views_dir: Path = VIEWS_DIR) -> list[Path]:
    return sorted(views_dir.glob("*.sql"))


def apply_views(database_url: str, views_dir: Path = VIEWS_DIR) -> list[str]:
    """Apply all view files in one transaction; return the file names applied."""
    files = view_files(views_dir)
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            # Raw DBAPI cursor, called with no parameters: neither SQLAlchemy
            # nor psycopg2 then parses ':' or '%' (both appear in the views'
            # header comments). Same connection, so still one transaction.
            cursor = conn.connection.cursor()
            for path in files:
                cursor.execute(path.read_text())
            cursor.close()
    finally:
        engine.dispose()
    return [p.name for p in files]


def main() -> None:
    from src.utils.config import get_settings

    applied = apply_views(get_settings().database_url)
    for name in applied:
        print(f"applied {name}")
    print(f"{len(applied)} views applied")


if __name__ == "__main__":
    main()
