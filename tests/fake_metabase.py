"""An in-memory fake of the Metabase REST API, just enough for the provisioner.

Stands in for `requests.Session`: `.request(method, url, json=, timeout=)`
and `.headers`. Records every call so tests can assert which writes happened.
"""

import copy
import json
import re
from urllib.parse import urlparse


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""
        self.content = self.text.encode()

    def json(self):
        return copy.deepcopy(self._payload)


class FakeMetabase:
    def __init__(self, admin_email="fake@example.com", admin_password="demo-only-admin"):
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, str, object]] = []
        self.setup_done = False
        self.admin = (admin_email, admin_password)
        self.setup_error_body: str | None = None  # make /api/setup fail with this body
        self.next_id = 100
        self.databases: dict[int, dict] = {}
        self.collections: dict[int, dict] = {}
        self.cards: dict[int, dict] = {}
        self.dashboards: dict[int, dict] = {}
        self.settings = {"enable-public-sharing": False}

    # -- helpers for tests ---------------------------------------------- #

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def add_collection(self, name: str) -> int:
        cid = self._id()
        self.collections[cid] = {"id": cid, "name": name, "location": "/", "archived": False}
        return cid

    def add_card(self, name: str, description: str, collection_id: int | None) -> int:
        cid = self._id()
        self.cards[cid] = {
            "id": cid,
            "name": name,
            "description": description,
            "collection_id": collection_id,
            "display": "table",
            "visualization_settings": {},
            "dataset_query": {},
            "database_id": None,
        }
        return cid

    def writes(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in self.calls if m in ("POST", "PUT", "DELETE")]

    def content_writes(self) -> list[tuple[str, str]]:
        return [
            (m, p)
            for m, p in self.writes()
            if not (m == "POST" and (p == "/api/session" or p.endswith("/sync_schema")))
        ]

    # -- the API ------------------------------------------------------- #

    def request(self, method, url, json=None, timeout=None):  # noqa: A002 - mirrors requests
        parsed = urlparse(url)
        path = parsed.path
        self.calls.append((method, path + (f"?{parsed.query}" if parsed.query else ""), json))
        authed = self.headers.get("X-Metabase-Session") == "FAKESESSION"

        if path == "/api/session/properties" and method == "GET":
            return FakeResponse(
                200,
                {
                    "has-user-setup": self.setup_done,
                    "setup-token": "fake-token",
                    "enable-public-sharing": self.settings["enable-public-sharing"],
                },
            )
        if path == "/api/setup" and method == "POST":
            if self.setup_error_body is not None:
                return FakeResponse(400, {"message": self.setup_error_body})
            assert json["token"] == "fake-token"
            self.admin = (json["user"]["email"], json["user"]["password"])
            self.setup_done = True
            return FakeResponse(200, {"id": "setup-session"})
        if path == "/api/session" and method == "POST":
            if (json["username"], json["password"]) == self.admin and self.setup_done:
                return FakeResponse(200, {"id": "FAKESESSION"})
            return FakeResponse(401, {"errors": {"password": "did not match stored password"}})
        if not authed:
            return FakeResponse(401, "Unauthenticated")

        m = re.fullmatch(r"/api/(database|collection|card|dashboard)(?:/(\d+))?(/.*)?", path)
        if path == "/api/setting/enable-public-sharing":
            if method == "PUT":
                self.settings["enable-public-sharing"] = json["value"]
                return FakeResponse(204)
            return FakeResponse(204)  # like v0.64: the value is in /api/session/properties
        if not m:
            return FakeResponse(404, "API endpoint does not exist.")
        kind, ident, rest = m.group(1), m.group(2), m.group(3)
        store = {
            "database": self.databases,
            "collection": self.collections,
            "card": self.cards,
            "dashboard": self.dashboards,
        }[kind]

        if ident is None:
            if method == "GET":
                items = [copy.deepcopy(v) for v in store.values()]
                if kind == "database":
                    return FakeResponse(200, {"data": items})
                return FakeResponse(200, items)
            if method == "POST":
                new_id = self._id()
                obj = {"id": new_id, **copy.deepcopy(json)}
                if kind == "collection":
                    obj.update(location="/", archived=False)
                if kind == "dashboard":
                    obj.update(dashcards=[], public_uuid=None)
                if kind == "card":
                    obj["database_id"] = json["dataset_query"]["database"]
                store[new_id] = obj
                return FakeResponse(200, copy.deepcopy(obj))
        ident = int(ident)
        if ident not in store:
            return FakeResponse(404, "Not found.")
        obj = store[ident]

        if rest == "/items" and kind == "collection":
            items = []
            for model, objs in (("card", self.cards), ("dashboard", self.dashboards)):
                for o in objs.values():
                    if o.get("collection_id") == ident:
                        items.append(
                            {"id": o["id"], "model": model, "description": o.get("description")}
                        )
            return FakeResponse(200, {"data": items, "total": len(items)})
        if rest == "/sync_schema":
            return FakeResponse(200, {"status": "ok"})
        if rest == "/public_link" and kind == "dashboard":
            if method == "POST":
                obj["public_uuid"] = f"fake-uuid-{ident}"
                return FakeResponse(200, {"uuid": obj["public_uuid"]})
            if method == "DELETE":
                obj["public_uuid"] = None
                return FakeResponse(204)
        if rest:
            return FakeResponse(404, "API endpoint does not exist.")

        if method == "GET":
            out = copy.deepcopy(obj)
            if kind == "database":
                out["details"] = {**out["details"], "password": "**MetabasePass**"}
            return FakeResponse(200, out)
        if method == "DELETE":
            del store[ident]
            return FakeResponse(204)
        if method == "PUT":
            if kind == "dashboard" and "dashcards" in json:
                dashcards = []
                for dc in json["dashcards"]:
                    dc = copy.deepcopy(dc)
                    if dc["id"] < 0:
                        dc["id"] = self._id()
                    dashcards.append(dc)
                obj["dashcards"] = dashcards
            else:
                for k, v in json.items():
                    obj[k] = copy.deepcopy(v) if k != "details" else {**obj["details"], **v}
            return FakeResponse(200, copy.deepcopy(obj))
        return FakeResponse(405, "Method not allowed")
