"""USAJobs Search API client.

Wraps https://data.usajobs.gov/api/search with the same politeness
controls as AdzunaClient: minimum interval between requests,
exponential-backoff retries on 429/5xx, a hard per-run call budget, and
request logging.

Auth is three required HTTP headers (per USAJobs' own docs at
developer.usajobs.gov/Guides/Authentication) rather than query params:
  Host              -- always "data.usajobs.gov"
  User-Agent        -- the email address used to request the API key
  Authorization-Key -- the API key itself
Both credentials are read from the environment and never logged.

The client returns raw dicts; all parsing lives in `usajobs_parser.py`
so it can be unit-tested without network access.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://data.usajobs.gov/api/search"
HOST = "data.usajobs.gov"

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class USAJobsError(RuntimeError):
    """Raised on non-retryable API failures or exhausted retries."""


class CallBudgetExceeded(USAJobsError):
    """Raised when the per-run API call budget would be exceeded."""


class USAJobsClient:
    """Thin, well-behaved wrapper around the USAJobs search endpoint."""

    def __init__(
        self,
        api_key: str,
        user_agent_email: str,
        min_request_interval: float = 1.0,
        max_calls: int = 100,
        max_retries: int = 4,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key or not user_agent_email:
            raise USAJobsError("USAJobs api_key and user_agent_email are required.")
        self._api_key = api_key
        self._user_agent_email = user_agent_email
        self.min_request_interval = min_request_interval
        self.max_calls = max_calls
        self.max_retries = max_retries
        self.timeout = timeout
        self._session = session or requests.Session()
        self._last_request_at: float = 0.0
        self.calls_made: int = 0

    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        page: int = 1,
        results_per_page: int = 25,
        **filters: Any,
    ) -> dict:
        """Fetch one page of search results as the raw response dict.

        `filters` are passed through as query params (e.g. `LocationName`,
        `DatePosted`). `Fields=Full` is requested explicitly so the
        response always includes `UserArea.Details` (the full narrative
        fields) rather than whatever USAJobs treats as the default.
        """
        params: dict[str, Any] = {
            "Keyword": query,
            "Page": page,
            "ResultsPerPage": results_per_page,
            "Fields": "Full",
            **filters,
        }
        return self._get(BASE_URL, params)

    def iter_search(
        self,
        query: str,
        max_results: int = 1000,
        results_per_page: int = 25,
        **filters: Any,
    ) -> Iterator[tuple[int, dict]]:
        """Paginate through search results.

        Yields `(page_number, raw_response_dict)` so the caller can
        persist each raw page verbatim. Stops when `max_results` is
        reached, a page comes back empty, or the API reports no more
        results.
        """
        fetched = 0
        page = 1
        while fetched < max_results:
            response = self.search(query, page=page, results_per_page=results_per_page, **filters)
            items = response.get("SearchResult", {}).get("SearchResultItems", [])
            if not items:
                logger.info("Query %r: page %d empty, stopping.", query, page)
                break
            yield page, response
            fetched += len(items)
            total_available = response.get("SearchResult", {}).get("SearchResultCountAll", 0)
            if fetched >= total_available:
                logger.info("Query %r: exhausted all %d available results.", query, total_available)
                break
            page += 1

    # ------------------------------------------------------------------ #

    def _get(self, url: str, params: dict) -> dict:
        if self.calls_made >= self.max_calls:
            raise CallBudgetExceeded(
                f"Per-run call budget of {self.max_calls} reached. "
                f"Raise --max-calls deliberately if this is intended."
            )

        self._throttle()

        headers = {
            "Host": HOST,
            "User-Agent": self._user_agent_email,
            "Authorization-Key": self._api_key,
        }

        backoff = 2.0
        for attempt in range(1, self.max_retries + 1):
            self._last_request_at = time.monotonic()
            self.calls_made += 1
            try:
                resp = self._session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                logger.warning("Request error (attempt %d): %s", attempt, exc)
                if attempt == self.max_retries:
                    raise USAJobsError(f"Network error after {attempt} attempts: {exc}") from exc
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 200:
                data = resp.json()
                n = len(data.get("SearchResult", {}).get("SearchResultItems", []))
                logger.info("GET %s -> 200 (%d results)", url, n)
                return data

            if resp.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                logger.warning(
                    "GET %s -> %d, retrying in %.1fs (attempt %d/%d)",
                    url,
                    resp.status_code,
                    backoff,
                    attempt,
                    self.max_retries,
                )
                time.sleep(backoff)
                backoff *= 2
                continue

            raise USAJobsError(
                f"USAJobs API returned {resp.status_code} for {url}: {resp.text[:300]}"
            )

        raise USAJobsError(f"Exhausted {self.max_retries} retries for {url}")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.min_request_interval - elapsed
        if wait > 0:
            time.sleep(wait)
