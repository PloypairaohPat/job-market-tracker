"""Behavioral tests for USAJobsClient — no network; uses a stub session."""

import json
from pathlib import Path

import pytest

from src.ingestion.usajobs_client import CallBudgetExceeded, USAJobsClient, USAJobsError

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

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return self.responses.pop(0)


def make_client(session, **kw) -> USAJobsClient:
    defaults = dict(
        api_key="key", user_agent_email="me@example.com", min_request_interval=0.0, session=session
    )
    defaults.update(kw)
    return USAJobsClient(**defaults)


def load_page() -> dict:
    return json.loads((FIXTURES / "usajobs_sample_response.json").read_text())


def test_requires_credentials():
    with pytest.raises(USAJobsError):
        USAJobsClient(api_key="", user_agent_email="me@example.com")
    with pytest.raises(USAJobsError):
        USAJobsClient(api_key="key", user_agent_email="")


def test_search_returns_payload_and_sends_auth_headers():
    session = StubSession(
        [StubResponse(200, {"SearchResult": {"SearchResultItems": [{"MatchedObjectId": "1"}]}})]
    )
    client = make_client(session)
    data = client.search("data analyst")
    assert len(data["SearchResult"]["SearchResultItems"]) == 1
    assert client.calls_made == 1

    url, params, headers = session.calls[0]
    # credentials go in headers, never in query params or the URL
    assert "key" not in url
    assert headers["Host"] == "data.usajobs.gov"
    assert headers["User-Agent"] == "me@example.com"
    assert headers["Authorization-Key"] == "key"
    assert params["Keyword"] == "data analyst"
    assert params["Fields"] == "Full"


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    session = StubSession(
        [
            StubResponse(429),
            StubResponse(200, {"SearchResult": {"SearchResultItems": [{"MatchedObjectId": "1"}]}}),
        ]
    )
    client = make_client(session)
    data = client.search("q")
    assert data["SearchResult"]["SearchResultItems"][0]["MatchedObjectId"] == "1"
    assert client.calls_made == 2


def test_non_retryable_error_raises_immediately():
    session = StubSession([StubResponse(401, {"error": "bad key"})])
    client = make_client(session)
    with pytest.raises(USAJobsError, match="401"):
        client.search("q")
    assert client.calls_made == 1  # no retries on auth failure


def test_call_budget_enforced():
    session = StubSession([StubResponse(200, {"SearchResult": {"SearchResultItems": []}})])
    client = make_client(session, max_calls=1)
    client.search("q")
    with pytest.raises(CallBudgetExceeded):
        client.search("q")


def test_iter_search_paginates_and_stops_at_count():
    page1 = {
        "SearchResult": {
            "SearchResultCountAll": 2,
            "SearchResultItems": [{"MatchedObjectId": "1"}],
        }
    }
    page2 = {
        "SearchResult": {
            "SearchResultCountAll": 2,
            "SearchResultItems": [{"MatchedObjectId": "2"}],
        }
    }
    session = StubSession([StubResponse(200, page1), StubResponse(200, page2)])
    client = make_client(session)
    pages = list(client.iter_search("data analyst", max_results=500, results_per_page=1))
    assert [p for p, _ in pages] == [1, 2]
    assert client.calls_made == 2  # did not request a third page


def test_iter_search_respects_max_results():
    page1 = load_page()
    session = StubSession([StubResponse(200, page1)])
    client = make_client(session)
    pages = list(client.iter_search("q", max_results=25, results_per_page=25))
    assert len(pages) == 1
    assert client.calls_made == 1


def test_iter_search_stops_on_empty_page():
    session = StubSession(
        [StubResponse(200, {"SearchResult": {"SearchResultCountAll": 999, "SearchResultItems": []}})]
    )
    client = make_client(session)
    assert list(client.iter_search("q")) == []
