"""Fake HTTP sessions for the run-log, budget and daily-runner tests.

They stand in for `requests.Session` inside the REAL AdzunaClient /
USAJobsClient, so call counting, retries and error text go through
production code. Nothing here touches the network. Credentials used with
them are obviously fake (FAKEID, FAKEKEY, fake@example.com).
"""

import copy
import json
from pathlib import Path

import requests

from src.ingestion.adzuna_client import AdzunaClient
from src.ingestion.usajobs_client import USAJobsClient

FIXTURES = Path(__file__).parent / "fixtures"
ADZUNA_PAGES = [
    json.loads((FIXTURES / "adzuna_page_1.json").read_text()),
    json.loads((FIXTURES / "adzuna_page_2.json").read_text()),
]
USAJOBS_PAGE = json.loads((FIXTURES / "usajobs_sample_response.json").read_text())


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)[:300]

    def json(self):
        return copy.deepcopy(self._payload)


class FakeAdzunaHTTP:
    """Serves fixture page 1 and 2, then an empty page."""

    def __init__(self):
        self.urls: list[str] = []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        page = int(url.rstrip("/").rsplit("/", 1)[1])
        if page <= len(ADZUNA_PAGES):
            return FakeResponse(ADZUNA_PAGES[page - 1])
        return FakeResponse({"count": 1243, "results": []})


class FakeUSAJobsHTTP:
    """Serves the USAJobs fixture as page 1, then an empty page."""

    def get(self, url, params=None, headers=None, timeout=None):
        if (params or {}).get("Page", 1) == 1:
            return FakeResponse(USAJOBS_PAGE)
        return FakeResponse(
            {"SearchResult": {"SearchResultCountAll": 234, "SearchResultItems": []}}
        )


class RaisingHTTP:
    """Raises the kind of error requests raises on a network blip: its
    message embeds the full URL, query string (and so credentials) included."""

    def get(self, url, params=None, headers=None, timeout=None):
        query = "&".join(f"{k}={v}" for k, v in (params or {}).items())
        raise requests.ConnectionError(
            f"HTTPSConnectionPool(host='127.0.0.1', port=9): Max retries exceeded with url: "
            f"{url}?{query} (Caused by NewConnectionError('Connection refused'))"
        )


def adzuna_client(http=None, max_calls: int = 60) -> AdzunaClient:
    return AdzunaClient(
        app_id="FAKEID",
        app_key="FAKEKEY",
        min_request_interval=0.0,
        max_calls=max_calls,
        max_retries=1,
        session=http or FakeAdzunaHTTP(),
    )


def usajobs_client(http=None, max_calls: int = 60) -> USAJobsClient:
    return USAJobsClient(
        api_key="FAKEUSAJOBSKEY",
        user_agent_email="fake@example.com",
        min_request_interval=0.0,
        max_calls=max_calls,
        max_retries=1,
        session=http or FakeUSAJobsHTTP(),
    )
