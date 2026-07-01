"""Behavioral tests for AdzunaClient — no network; uses a stub session."""

import json
from pathlib import Path

import pytest

from src.ingestion.adzuna_client import AdzunaClient, AdzunaError, CallBudgetExceeded

FIXTURES = Path(__file__).parent / "fixtures"


class StubResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)[:300]

    def json(self):
        return self._payload


class StubSession:
    """Returns queued responses in order; records calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


def make_client(session, **kw) -> AdzunaClient:
    defaults = dict(app_id="id", app_key="key", min_request_interval=0.0, session=session)
    defaults.update(kw)
    return AdzunaClient(**defaults)


def load_page(n: int) -> dict:
    return json.loads((FIXTURES / f"adzuna_page_{n}.json").read_text())


def test_requires_credentials():
    with pytest.raises(AdzunaError):
        AdzunaClient(app_id="", app_key="key")


def test_search_returns_payload():
    session = StubSession([StubResponse(200, {"count": 1, "results": [{"id": "1"}]})])
    client = make_client(session)
    data = client.search("data analyst")
    assert data["count"] == 1
    assert client.calls_made == 1
    # credentials go in params, never in the URL path
    url, params = session.calls[0]
    assert "app_key" not in url and params["app_key"] == "key"


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    session = StubSession(
        [
            StubResponse(429),
            StubResponse(200, {"results": [{"id": "1"}]}),
        ]
    )
    client = make_client(session)
    data = client.search("q")
    assert data["results"][0]["id"] == "1"
    assert client.calls_made == 2


def test_non_retryable_error_raises_immediately():
    session = StubSession([StubResponse(401, {"error": "bad key"})])
    client = make_client(session)
    with pytest.raises(AdzunaError, match="401"):
        client.search("q")
    assert client.calls_made == 1  # no retries on auth failure


def test_call_budget_enforced():
    session = StubSession([StubResponse(200, {"results": []})])
    client = make_client(session, max_calls=1)
    client.search("q")
    with pytest.raises(CallBudgetExceeded):
        client.search("q")


def test_iter_search_paginates_and_stops_at_count():
    page1, page2 = load_page(1), load_page(2)
    page2["count"] = 100  # exactly two pages of 50 available
    page1["count"] = 100
    session = StubSession([StubResponse(200, page1), StubResponse(200, page2)])
    client = make_client(session)
    pages = list(client.iter_search("data analyst", max_results=500))
    assert [p for p, _ in pages] == [1, 2]
    assert client.calls_made == 2  # did not request a third page


def test_iter_search_respects_max_results():
    page1 = load_page(1)
    session = StubSession([StubResponse(200, page1)])
    client = make_client(session)
    pages = list(client.iter_search("q", max_results=50))
    assert len(pages) == 1
    assert client.calls_made == 1


def test_iter_search_stops_on_empty_page():
    session = StubSession([StubResponse(200, {"count": 999, "results": []})])
    client = make_client(session)
    assert list(client.iter_search("q")) == []
