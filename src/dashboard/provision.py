"""Build every Metabase dashboard from `dashboards/` through the REST API.

Run:  python -m src.dashboard.provision [--dry-run] [--public-links] [--reconnect]
      (or: make bi-provision; Metabase must be up: docker compose --profile bi up -d)

Written against Metabase v0.64.3.4 (the pinned image), checked against that
version's /api/docs/openapi.json: cards carry an MBQL 5 native query
(`{"lib/type": "mbql/query", "stages": [{"lib/type": "mbql.stage/native",
...}]}`), and a dashboard's cards are saved with PUT /api/dashboard/{id}
{"dashcards": [...]} (negative ids = new). Re-check both when bumping the image.

Steps, all idempotent:
  1. First run on a fresh Metabase: complete setup with METABASE_ADMIN_EMAIL /
     METABASE_ADMIN_PASSWORD. Then log in.
  2. Ensure the database connection "Job Market Tracker (<db>)" as the
     read-only role (METABASE_DB_HOST default `db`, METABASE_DB_PORT default
     5432, METABASE_DB_NAME default from DATABASE_URL, METABASE_DB_USER default
     metabase_reader, password METABASE_READER_PASSWORD), and trigger a sync.
  3. Ensure the collection "Job Market Tracker". Inside it, create or update
     every card and dashboard in the spec, matched by its stable key: each
     description ends with "Defined in dashboards/sql/<key>.sql" (cards) or
     "Defined in dashboards/<slug>.json" (dashboards). Items in the collection
     that carry such a line but are no longer in the spec are deleted; nothing
     outside the collection, and nothing without the line, is ever touched.
  4. A target database whose name contains "demo" or "test" gets a top banner
     on every dashboard: "DEMO DATA: synthetic, not market findings".
  5. --public-links turns public sharing on and creates links for dashboards
     marked public: true. Off by default (parked until the Hetzner deploy).
     A dashboard marked public: false never keeps a public link.

A second run with an unchanged spec makes no write call (the sync aside).
--dry-run logs every write it would make and makes none. Secrets are masked
in all output (RedactingFilter); network errors exit non-zero with a clear
message.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

import requests
from sqlalchemy.engine import make_url

from src.dashboard.spec import DASHBOARDS_DIR, GRID_COLUMNS, Card, card_sql, load_and_validate
from src.utils.redaction import install_redaction, redact

logger = logging.getLogger("src.dashboard.provision")

COLLECTION_NAME = "Job Market Tracker"
DEMO_BANNER = "DEMO DATA: synthetic, not market findings"
BANNER_HEIGHT = 2
CARD_MARKER = re.compile(r"Defined in dashboards/sql/([\w-]+)\.sql")
DASHBOARD_MARKER = re.compile(r"Defined in dashboards/([\w-]+)\.json")
WRITE_METHODS = {"POST", "PUT", "DELETE"}


class ProvisionError(RuntimeError):
    pass


@dataclass
class Config:
    url: str = "http://localhost:3000"
    admin_email: str = ""
    admin_password: str = ""
    reader_password: str = ""
    db_host: str = "db"
    db_port: int = 5432
    db_name: str = ""
    db_user: str = "metabase_reader"
    site_name: str = "Job Market Tracker"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        env = dict(os.environ if env is None else env)
        db_name = env.get("METABASE_DB_NAME", "")
        if not db_name and env.get("DATABASE_URL"):
            db_name = make_url(env["DATABASE_URL"]).database or ""
        return cls(
            url=(env.get("METABASE_URL") or cls.url).rstrip("/"),
            admin_email=env.get("METABASE_ADMIN_EMAIL", ""),
            admin_password=env.get("METABASE_ADMIN_PASSWORD", ""),
            reader_password=env.get("METABASE_READER_PASSWORD", ""),
            db_host=env.get("METABASE_DB_HOST") or cls.db_host,
            db_port=int(env.get("METABASE_DB_PORT") or cls.db_port),
            db_name=db_name,
            db_user=env.get("METABASE_DB_USER") or cls.db_user,
        )

    def missing(self) -> list[str]:
        required = {
            "METABASE_ADMIN_EMAIL": self.admin_email,
            "METABASE_ADMIN_PASSWORD": self.admin_password,
            "METABASE_READER_PASSWORD": self.reader_password,
            "METABASE_DB_NAME (or DATABASE_URL)": self.db_name,
        }
        return [name for name, value in required.items() if not value]

    @property
    def secrets(self) -> list[str]:
        return [self.admin_password, self.reader_password]

    @property
    def is_demo(self) -> bool:
        return "demo" in self.db_name or "test" in self.db_name

    @property
    def database_display_name(self) -> str:
        return f"Job Market Tracker ({self.db_name})"


@dataclass
class Result:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    card_ids: dict[str, int] = field(default_factory=dict)
    dashboard_ids: dict[str, int] = field(default_factory=dict)
    public_urls: dict[str, str] = field(default_factory=dict)
    planned: list[str] = field(default_factory=list)  # dry-run: writes not made


# --------------------------------------------------------------------- #
# HTTP


class Api:
    """Thin requests wrapper: JSON in/out, redacted errors, dry-run for writes."""

    def __init__(self, base: str, session, secrets: list[str], dry_run: bool, result: Result):
        self.base = base
        self.session = session
        self.secrets = [s for s in secrets if s]
        self.dry_run = dry_run
        self.result = result

    def _safe(self, text: str) -> str:
        return redact(text, self.secrets)

    def call(self, method: str, path: str, payload: Any = None, *, write: bool | None = None):
        is_write = method in WRITE_METHODS if write is None else write
        if is_write and self.dry_run:
            self.result.planned.append(f"{method} {path}")
            logger.info("[dry-run] would %s %s", method, path)
            return None
        try:
            resp = self.session.request(method, self.base + path, json=payload, timeout=60)
        except requests.RequestException as exc:
            raise ProvisionError(
                f"cannot reach Metabase at {self.base} ({type(exc).__name__}): "
                f"{self._safe(str(exc))}. Is it running? docker compose --profile bi up -d"
            ) from None
        if resp.status_code >= 400:
            raise ProvisionError(
                f"{method} {path} -> HTTP {resp.status_code}: {self._safe(resp.text[:500])}"
            )
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def get(self, path: str):
        return self.call("GET", path)

    def post(self, path: str, payload: Any = None, *, write: bool | None = None):
        return self.call("POST", path, payload, write=write)

    def put(self, path: str, payload: Any):
        return self.call("PUT", path, payload)

    def delete(self, path: str):
        return self.call("DELETE", path)


def _items(response) -> list[dict]:
    """List endpoints return either a list or {"data": [...]}."""
    if isinstance(response, dict):
        return response.get("data") or []
    return response or []


# --------------------------------------------------------------------- #


def card_description(card: Card) -> str:
    return (
        f"{card.description}\n\nDefined in dashboards/sql/{card.key}.sql "
        "(provisioned from the repo: edit the file and re-run provision; edits made here are "
        "overwritten)."
    )


def dashboard_description(slug: str, description: str) -> str:
    return (
        f"{description}\n\nDefined in dashboards/{slug}.json (provisioned from the repo: edit the "
        "file and re-run provision; edits made here are overwritten)."
    )


def text_viz(text: str) -> dict:
    return {
        "virtual_card": {
            "name": None,
            "display": "text",
            "visualization_settings": {},
            "dataset_query": {},
            "archived": False,
        },
        "text": text,
    }


def native_query(database_id: int, sql: str) -> dict:
    return {
        "lib/type": "mbql/query",
        "database": database_id,
        "stages": [{"lib/type": "mbql.stage/native", "native": sql, "template-tags": {}}],
    }


def _current_sql(card: dict) -> str | None:
    dq = card.get("dataset_query") or {}
    stages = dq.get("stages") or []
    if stages and stages[0].get("lib/type") == "mbql.stage/native":
        return stages[0].get("native")
    return (dq.get("native") or {}).get("query")  # legacy shape


class Provisioner:
    def __init__(
        self,
        config: Config,
        session=None,
        *,
        dry_run: bool = False,
        public_links: bool = False,
        reconnect: bool = False,
        dashboards_dir=DASHBOARDS_DIR,
    ):
        self.config = config
        self.dry_run = dry_run
        self.public_links = public_links
        self.reconnect = reconnect
        self.dashboards_dir = dashboards_dir
        self.result = Result()
        self.api = Api(
            config.url, session or requests.Session(), config.secrets, dry_run, self.result
        )

    # -- steps ---------------------------------------------------------- #

    def run(self) -> Result:
        missing = self.config.missing()
        if missing:
            raise ProvisionError(f"missing required setting(s): {', '.join(missing)} (see .env)")
        dashboards = load_and_validate(self.dashboards_dir)
        if not self.ensure_setup_and_login():
            return self.result
        db_id = self.ensure_database()
        collection_id = self.ensure_collection()
        if collection_id is None:  # dry run on an instance without the collection yet
            for d in dashboards:
                self.result.planned.append(f"create dashboard {d.slug} and its cards")
            return self.result
        existing_cards, existing_dashboards = self.collection_contents(collection_id)
        for dash in dashboards:
            dashcards = []
            for card in dash.cards:
                if card.is_question:
                    card_id = self.ensure_card(card, db_id, collection_id, existing_cards)
                    dashcards.append((card, card_id))
                else:
                    dashcards.append((card, None))
            self.ensure_dashboard(dash, dashcards, collection_id, existing_dashboards)
        self.prune(dashboards, existing_cards, existing_dashboards)
        return self.result

    def ensure_setup_and_login(self) -> bool:
        props = self.api.get("/api/session/properties") or {}
        if not props.get("has-user-setup"):
            logger.info("fresh Metabase: running first-time setup as %s", self.config.admin_email)
            self.api.post(
                "/api/setup",
                {
                    "token": props.get("setup-token"),
                    "user": {
                        "email": self.config.admin_email,
                        "password": self.config.admin_password,
                        "first_name": "Job Market",
                        "last_name": "Tracker",
                    },
                    "prefs": {"site_name": self.config.site_name, "site_locale": "en"},
                },
            )
            self.result.created.append("setup")
            if self.dry_run:
                logger.info("[dry-run] stopping: nothing more to inspect before setup")
                return False
        session = self.api.post(
            "/api/session",
            {"username": self.config.admin_email, "password": self.config.admin_password},
            write=False,
        )
        token = (session or {}).get("id")
        if not token:
            raise ProvisionError("login returned no session id")
        self.api.secrets.append(token)
        install_redaction([token])
        self.api.session.headers["X-Metabase-Session"] = token
        return True

    def ensure_database(self) -> int | None:
        c = self.config
        details = {
            "host": c.db_host,
            "port": c.db_port,
            "dbname": c.db_name,
            "user": c.db_user,
            "password": c.reader_password,
            "ssl": False,
            "tunnel-enabled": False,
        }
        existing = [
            d
            for d in _items(self.api.get("/api/database"))
            if d.get("name") == c.database_display_name
        ]
        if not existing:
            created = self.api.post(
                "/api/database",
                {"name": c.database_display_name, "engine": "postgres", "details": details},
            )
            self.result.created.append(f"database {c.database_display_name}")
            db_id = (created or {}).get("id")
        else:
            db_id = existing[0]["id"]
            current = self.api.get(f"/api/database/{db_id}").get("details") or {}
            same = all(
                str(current.get(k)) == str(details[k]) for k in ("host", "port", "dbname", "user")
            )
            if self.reconnect or not same:
                self.api.put(f"/api/database/{db_id}", {"details": details})
                self.result.updated.append(f"database {c.database_display_name}")
            else:
                self.result.unchanged.append(f"database {c.database_display_name}")
        if db_id is not None:
            self.api.post(f"/api/database/{db_id}/sync_schema")  # a write: skipped in dry runs
        return db_id

    def ensure_collection(self) -> int | None:
        for coll in _items(self.api.get("/api/collection")):
            if (
                coll.get("name") == COLLECTION_NAME
                and not coll.get("archived")
                and coll.get("location", "/") == "/"
                and isinstance(coll.get("id"), int)
            ):
                self.result.unchanged.append("collection")
                return coll["id"]
        created = self.api.post(
            "/api/collection",
            {
                "name": COLLECTION_NAME,
                "description": "Provisioned from the repo's dashboards/ by src/dashboard/provision.py",
            },
        )
        self.result.created.append("collection")
        return (created or {}).get("id")

    def collection_contents(self, collection_id: int) -> tuple[dict, dict]:
        """{key: [card dict, ...]}, {slug: [dashboard dict, ...]} for marked items."""
        cards: dict[str, list[dict]] = {}
        dashboards: dict[str, list[dict]] = {}
        listing = self.api.get(
            f"/api/collection/{collection_id}/items?models=card&models=dashboard"
        )
        for item in _items(listing):
            desc = item.get("description") or ""
            if item.get("model") == "card" and (m := CARD_MARKER.search(desc)):
                cards.setdefault(m.group(1), []).append(self.api.get(f"/api/card/{item['id']}"))
            elif item.get("model") == "dashboard" and (m := DASHBOARD_MARKER.search(desc)):
                dashboards.setdefault(m.group(1), []).append(
                    self.api.get(f"/api/dashboard/{item['id']}")
                )
        for group in (cards, dashboards):
            for items in group.values():
                items.sort(key=lambda x: x["id"])
        return cards, dashboards

    def ensure_card(self, card: Card, db_id: int, collection_id: int, existing: dict) -> int | None:
        sql = card_sql(card, self.dashboards_dir).strip()
        desired = {
            "name": card.title,
            "description": card_description(card),
            "display": card.display,
            "visualization_settings": card.visualization_settings,
            "collection_id": collection_id,
            "dataset_query": native_query(db_id, sql),
        }
        found = existing.get(card.key) or []
        if not found:
            created = self.api.post("/api/card", desired)
            self.result.created.append(f"card {card.key}")
            card_id = (created or {}).get("id")
        else:
            current = found[0]
            card_id = current["id"]
            viz = current.get("visualization_settings") or {}
            same = (
                current.get("name") == desired["name"]
                and current.get("description") == desired["description"]
                and current.get("display") == desired["display"]
                and current.get("collection_id") == collection_id
                and (_current_sql(current) or "").strip() == sql
                and current.get("database_id") in (db_id, None)
                and all(viz.get(k) == v for k, v in card.visualization_settings.items())
            )
            if same:
                self.result.unchanged.append(f"card {card.key}")
            else:
                self.api.put(f"/api/card/{card_id}", desired)
                self.result.updated.append(f"card {card.key}")
        if card_id is not None:
            self.result.card_ids[card.key] = card_id
        return card_id

    def _desired_dashcards(self, cards: list[tuple[Card, int | None]]) -> list[dict]:
        shift = BANNER_HEIGHT if self.config.is_demo else 0
        out = []
        if shift:
            out.append(
                {"card_id": None, "row": 0, "col": 0, "size_x": GRID_COLUMNS,
                 "size_y": BANNER_HEIGHT, "text": f"## {DEMO_BANNER}"}
            )  # fmt: skip
        for card, card_id in cards:
            out.append(
                {
                    "card_id": card_id,
                    "row": card.row + shift,
                    "col": card.col,
                    "size_x": card.width,
                    "size_y": card.height,
                    "text": None if card.is_question else card.text,
                }
            )
        return out

    @staticmethod
    def _signature(dashcards: list[dict]) -> list[tuple]:
        return sorted(
            (
                d.get("card_id") or 0,
                d["row"],
                d["col"],
                d["size_x"],
                d["size_y"],
                d.get("text") or "",
            )
            for d in dashcards
        )

    def ensure_dashboard(self, dash, cards, collection_id: int, existing: dict) -> None:
        description = dashboard_description(dash.slug, dash.description)
        found = existing.get(dash.slug) or []
        if not found:
            created = self.api.post(
                "/api/dashboard",
                {"name": dash.name, "description": description, "collection_id": collection_id},
            )
            self.result.created.append(f"dashboard {dash.slug}")
            current = {"id": (created or {}).get("id"), "dashcards": []}
        else:
            current = found[0]
            if (
                current.get("name") != dash.name
                or current.get("description") != description
                or current.get("collection_id") != collection_id
            ):
                self.api.put(
                    f"/api/dashboard/{current['id']}",
                    {"name": dash.name, "description": description, "collection_id": collection_id},
                )
                self.result.updated.append(f"dashboard {dash.slug}")
        dash_id = current.get("id")

        desired = self._desired_dashcards(cards)
        existing_cards = [
            {
                "id": dc["id"],
                "card_id": dc.get("card_id"),
                "row": dc["row"],
                "col": dc["col"],
                "size_x": dc["size_x"],
                "size_y": dc["size_y"],
                "text": (dc.get("visualization_settings") or {}).get("text")
                if dc.get("card_id") is None
                else None,
            }
            for dc in current.get("dashcards") or []
        ]
        if self._signature(existing_cards) == self._signature(desired):
            if found:
                self.result.unchanged.append(f"dashboard {dash.slug}")
        else:
            payload, next_new = [], -1
            reusable = list(existing_cards)
            for d in desired:
                match = next(
                    (
                        e
                        for e in reusable
                        if e["card_id"] == d["card_id"]
                        and (d["card_id"] is not None or e["text"] == d["text"])
                    ),
                    None,
                )
                if match:
                    reusable.remove(match)
                    dc_id = match["id"]
                else:
                    dc_id, next_new = next_new, next_new - 1
                payload.append(
                    {
                        "id": dc_id,
                        "card_id": d["card_id"],
                        "row": d["row"],
                        "col": d["col"],
                        "size_x": d["size_x"],
                        "size_y": d["size_y"],
                        "visualization_settings": {} if d["card_id"] else text_viz(d["text"]),
                        "parameter_mappings": [],
                        "series": [],
                    }
                )
            if dash_id is not None:
                self.api.put(f"/api/dashboard/{dash_id}", {"dashcards": payload})
            if found:
                self.result.updated.append(f"dashboard {dash.slug} layout")
        if dash_id is not None:
            self.result.dashboard_ids[dash.slug] = dash_id
            self.ensure_public_link(dash, current)

    def ensure_public_link(self, dash, current: dict) -> None:
        uuid = current.get("public_uuid")
        if not dash.public:
            if uuid:  # a private dashboard never keeps a public link
                self.api.delete(f"/api/dashboard/{current['id']}/public_link")
                self.result.updated.append(f"dashboard {dash.slug} public link removed")
            return
        if not self.public_links:
            return
        setting = self.api.get("/api/setting/enable-public-sharing")
        if setting not in (True, "true"):
            self.api.put("/api/setting/enable-public-sharing", {"value": True})
            self.result.updated.append("setting enable-public-sharing")
        if not uuid:
            created = self.api.post(f"/api/dashboard/{current['id']}/public_link")
            uuid = (created or {}).get("uuid")
            self.result.created.append(f"dashboard {dash.slug} public link")
        if uuid:
            self.result.public_urls[dash.slug] = f"{self.config.url}/public/dashboard/{uuid}"

    def prune(self, dashboards, existing_cards: dict, existing_dashboards: dict) -> None:
        """Delete marked items no longer in the spec, and duplicates of kept ones."""
        slugs = {d.slug for d in dashboards}
        keys = {c.key for d in dashboards for c in d.cards if c.is_question}
        for slug, items in sorted(existing_dashboards.items()):
            extras = items if slug not in slugs else items[1:]
            for item in extras:
                self.api.delete(f"/api/dashboard/{item['id']}")
                self.result.deleted.append(f"dashboard {slug} (id {item['id']})")
        for key, items in sorted(existing_cards.items()):
            extras = items if key not in keys else items[1:]
            for item in extras:
                self.api.delete(f"/api/card/{item['id']}")
                self.result.deleted.append(f"card {key} (id {item['id']})")


# --------------------------------------------------------------------- #


def summarize(result: Result, dry_run: bool) -> str:
    lines = [
        f"created {len(result.created)}, updated {len(result.updated)}, "
        f"deleted {len(result.deleted)}, unchanged {len(result.unchanged)}"
    ]
    for label, items in (("created", result.created), ("updated", result.updated),
                         ("deleted", result.deleted)):  # fmt: skip
        lines += [f"  {label}: {item}" for item in items]
    if dry_run:
        lines.append(f"dry run: {len(result.planned)} write(s) not made")
        lines += [f"  would {p}" for p in result.planned]
    for slug, url in sorted(result.public_urls.items()):
        lines.append(f"  public link {slug}: {url}")
    return "\n".join(lines)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argp = argparse.ArgumentParser(description="Provision Metabase dashboards from dashboards/.")
    argp.add_argument("--dry-run", action="store_true", help="log the writes; make none")
    argp.add_argument(
        "--public-links",
        action="store_true",
        help="enable public sharing and link dashboards marked public: true (after Hetzner)",
    )
    argp.add_argument(
        "--reconnect",
        action="store_true",
        help="re-send the database connection details (e.g. after rotating the reader password)",
    )
    args = argp.parse_args()

    config = Config.from_env()
    install_redaction(config.secrets)
    try:
        result = Provisioner(
            config, dry_run=args.dry_run, public_links=args.public_links, reconnect=args.reconnect
        ).run()
    except ProvisionError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    logger.info("Metabase %s\n%s", config.url, summarize(result, args.dry_run))


if __name__ == "__main__":
    main()
