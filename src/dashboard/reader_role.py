"""Read-only Postgres role for Metabase: the `v_*` views and nothing else.

Run:  python -m src.dashboard.reader_role [--role NAME]     (or: make bi-grant)

Connects with DATABASE_URL (an owner connection) and, idempotently:
  1. creates the LOGIN role (default `metabase_reader`) or updates it,
     with its password from METABASE_READER_PASSWORD;
  2. grants CONNECT on the database and USAGE on schema public;
  3. revokes every table/sequence privilege it may have picked up, then
     grants SELECT on every view in schema public whose name starts with
     `v_` (enumerated from pg_views).

Views run with their owner's privileges (they are not security_invoker),
so the role reads every metric the SQL views expose while `SELECT ... FROM
jobs` fails with permission denied. That keeps "SQL views are the source
of truth" enforceable: a dashboard card can't quietly reimplement a metric
from base tables. Re-run after `make views` to pick up new views.

The password is sent once, inside the CREATE/ALTER ROLE statement, and is
never printed or logged.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from src.utils.config import get_settings
from src.utils.redaction import install_redaction

logger = logging.getLogger(__name__)

DEFAULT_ROLE = "metabase_reader"
PASSWORD_ENV = "METABASE_READER_PASSWORD"
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class ReaderRoleError(RuntimeError):
    pass


def _ident(name: str) -> str:
    """Role names are interpolated into DDL, so allow plain identifiers only."""
    if not _IDENT.match(name):
        raise ReaderRoleError(f"invalid role name {name!r}: use lowercase letters, digits, _")
    return f'"{name}"'


def reader_views(conn: Connection) -> list[str]:
    return list(
        conn.execute(
            text(
                "select viewname from pg_views where schemaname = 'public' "
                "and viewname like 'v\\_%' order by viewname"
            )
        ).scalars()
    )


def grant_reader(database_url: str, password: str, role: str = DEFAULT_ROLE) -> list[str]:
    """Create/update `role` and grant it SELECT on every v_* view. Returns the views."""
    if not password:
        raise ReaderRoleError(f"{PASSWORD_ENV} is empty; set it in .env first")
    quoted = _ident(role)
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text("select 1 from pg_roles where rolname = :r"), {"r": role}
            ).scalar()
            verb = "alter" if exists else "create"
            # Utility statements take no server-side parameters; psycopg2
            # interpolates :pw client-side as a properly quoted literal.
            conn.execute(
                text(
                    f"{verb} role {quoted} with login nosuperuser nocreatedb nocreaterole "
                    "noinherit password :pw"
                ),
                {"pw": password},
            )
            database = conn.execute(text("select current_database()")).scalar_one()
            conn.execute(text(f'grant connect on database "{database}" to {quoted}'))
            conn.execute(text(f"grant usage on schema public to {quoted}"))
            # nothing on any table, sequence or function -- then views only
            conn.execute(text(f"revoke all on all tables in schema public from {quoted}"))
            conn.execute(text(f"revoke all on all sequences in schema public from {quoted}"))
            views = reader_views(conn)
            for view in views:
                conn.execute(text(f'grant select on public."{view}" to {quoted}'))
    finally:
        engine.dispose()
    return views


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argp = argparse.ArgumentParser(description="Create/update the read-only Metabase role.")
    argp.add_argument("--role", default=DEFAULT_ROLE, help=f"role name (default {DEFAULT_ROLE})")
    args = argp.parse_args()

    password = os.environ.get(PASSWORD_ENV, "")
    install_redaction([password])
    try:
        views = grant_reader(get_settings().database_url, password, args.role)
    except ReaderRoleError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    logger.info("role %s can read %d views: %s", args.role, len(views), ", ".join(views))
    if not views:
        logger.warning("no v_* views found: run `make views` first, then re-run this")


if __name__ == "__main__":
    main()
