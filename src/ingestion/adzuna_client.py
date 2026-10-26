"""Adzuna API client.

Wraps the Adzuna job search API (https://developer.adzuna.com/) with:

- polite rate limiting (minimum interval between requests)
- exponential-backoff retries on 429 and 5xx responses
- a hard per-run call budget so a stray loop can never burn the
  1,000-calls/month free tier while iterating in development
- request logging (URL without credentials, status, result count)

The client returns raw dicts; all parsing lives in `adzuna_parser.py`
so it can be unit-tested without network access.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import requests

from src.utils.redaction import redact

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs"

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class AdzunaError(RuntimeError):
    """Raised on non-retryable API failures or exhausted retries."""


class CallBudgetExceeded(AdzunaError):
    """Raised when the per-run API call budget would be exceeded."""


class AdzunaClient:
    """Thin, well-behaved wrapper around the Adzuna search endpoint."""

    def __init__(
        self,
        app_id: str,
        app_key: str,
        country: str = "us",
        min_request_interval: float = 1.5,
        max_calls: int = 100,
        max_retries: int = 4,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        if not app_id or not app_key:
            raise AdzunaError("Adzuna app_id and app_key are required.")
        self._app_id = app_id
        self._app_key = app_key
        self.country = country
        self.min_request_interval = min_request_interval
        self.max_calls = max_calls
        self.max_retries = max_retries
        self.timeout = timeout
        self._session = session or requests.Session()
        self._last_request_at: float = 0.0
        self.calls_made: int = 0

    def credential_values(self) -> list[str]:
        """Secret values to mask in logs and stored errors (see src/utils/redaction.py)."""
        return [self._app_id, self._app_key]

    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str,
        page: int = 1,
        results_per_page: int = 50,
        **filters: Any,
    ) -> dict:
        """Fetch one page of search results as the raw response dict.

        `filters` are passed through as query params (e.g. `where`,
        `sort_by`, `max_days_old`). See Adzuna docs for the full list.
        """
        url = f"{BASE_URL}/{self.country}/search/{page}"
        params: dict[str, Any] = {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "what": query,
            "results_per_page": results_per_page,
            "content-type": "application/json",
            **filters,
        }
        return self._get(url, params)

    def iter_search(
        self,
        query: str,
        max_results: int = 1000,
        results_per_page: int = 50,
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
            results = response.get("results", [])
            if not results:
                logger.info("Query %r: page %d empty, stopping.", query, page)
                break
            yield page, response
            fetched += len(results)
            total_available = response.get("count", 0)
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

        backoff = 2.0
        for attempt in range(1, self.max_retries + 1):
            self._last_request_at = time.monotonic()
            self.calls_made += 1
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                # requests puts the full URL, query string included, in the
                # message -- for Adzuna that is the app_id/app_key. Mask it.
                detail = redact(str(exc), self.credential_values())
                logger.warning("Request error (attempt %d): %s", attempt, detail)
                if attempt == self.max_retries:
                    raise AdzunaError(f"Network error after {attempt} attempts: {detail}") from None
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 200:
                data = resp.json()
                logger.info("GET %s -> 200 (%d results)", url, len(data.get("results", [])))
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

            raise AdzunaError(
                f"Adzuna API returned {resp.status_code} for {url}: {resp.text[:300]}"
            )

        raise AdzunaError(f"Exhausted {self.max_retries} retries for {url}")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.min_request_interval - elapsed
        if wait > 0:
            time.sleep(wait)
