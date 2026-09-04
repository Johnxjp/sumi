"""A small HTTP client for the five Notion REST calls the sync needs.

Notion allows an average of three requests per second per integration, so
every call goes through a token bucket: a counter that refills at that rate
and that a request must take one token from, sleeping when there is none.
Over the limit Notion answers 429 with a `Retry-After` header in seconds.
"""

import time
from collections.abc import Callable, Iterator
from typing import Any, Self

import httpx

NOTION_API_BASE = "https://api.notion.com/v1"
# The version that introduced the whole-page markdown endpoint used below.
NOTION_VERSION = "2026-03-11"
SEARCH_PAGE_SIZE = 100
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 60.0
# Notion returns this code in a 403 when the workspace has no credits left for
# the endpoint. Every later request would fail the same way, so the run stops.
CREDITS_EXHAUSTED_CODE = "workspace_credits_exhausted"


class NotionError(Exception):
    """Any failed Notion request."""


class NotionAuthError(NotionError):
    """The secret, the page grant or the endpoint's entitlement is wrong."""


class NotionNotFoundError(NotionError):
    """The object does not exist, or the integration cannot see it."""


class TokenBucket:
    """Lets through `rate` calls per second on average, bursts up to `capacity`."""

    def __init__(
        self,
        rate: float,
        capacity: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        self.capacity = rate if capacity is None else capacity
        self._monotonic = monotonic
        self._sleep = sleep
        self._tokens = self.capacity
        self._updated = monotonic()

    def acquire(self) -> None:
        self._refill()
        if self._tokens < 1.0:
            self._sleep((1.0 - self._tokens) / self.rate)
            self._refill()
        self._tokens = max(0.0, self._tokens - 1.0)

    def _refill(self) -> None:
        now = self._monotonic()
        self._tokens = min(
            self.capacity, self._tokens + (now - self._updated) * self.rate
        )
        self._updated = now


class NotionClient:
    """Reads pages, data sources, databases and blocks from Notion's REST API."""

    def __init__(
        self,
        token: str,
        requests_per_second: float = 3.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        max_attempts: int = MAX_ATTEMPTS,
        base_url: str = NOTION_API_BASE,
    ):
        if not token:
            raise ValueError("A Notion integration secret is required.")
        self.request_count = 0
        self.max_attempts = max_attempts
        self._sleep = sleep
        self._bucket = TokenBucket(
            requests_per_second, monotonic=monotonic, sleep=sleep
        )
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def iter_search(self, kind: str = "page") -> Iterator[dict[str, Any]]:
        """Every object of that kind the integration can see, newest edit first.

        `kind` is Notion's object type: "page" or "data_source". The endpoint
        returns 100 per request and a cursor for the next page of results.
        """
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {
                "filter": {"property": "object", "value": kind},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": SEARCH_PAGE_SIZE,
            }
            if cursor is not None:
                body["start_cursor"] = cursor
            payload = self._request("POST", "/search", json=body)
            yield from payload.get("results") or []
            cursor = payload.get("next_cursor")
            if not payload.get("has_more") or not cursor:
                return

    def get_page_markdown(self, page_id: str) -> str:
        """The whole page as Notion's enhanced markdown, nested blocks included."""
        payload = self._request("GET", f"/pages/{page_id}/markdown")
        markdown = payload.get("markdown") or ""
        if not payload.get("truncated"):
            return markdown
        parts = [markdown]
        for block_id in payload.get("unknown_block_ids") or []:
            extra = self._request("GET", f"/pages/{block_id}/markdown")
            parts.append(extra.get("markdown") or "")
        return "\n".join(part for part in parts if part)

    def get_page(self, page_id: str) -> dict[str, Any]:
        return self._request("GET", f"/pages/{page_id}")

    def get_data_source(self, data_source_id: str) -> dict[str, Any]:
        return self._request("GET", f"/data_sources/{data_source_id}")

    def get_database(self, database_id: str) -> dict[str, Any]:
        return self._request("GET", f"/databases/{database_id}")

    def get_block(self, block_id: str) -> dict[str, Any]:
        return self._request("GET", f"/blocks/{block_id}")

    def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        last_status = 0
        for attempt in range(1, self.max_attempts + 1):
            self._bucket.acquire()
            self.request_count += 1
            response = self._client.request(method, path, json=json)
            last_status = response.status_code
            if response.is_success:
                return response.json()
            if response.status_code in (401, 403):
                raise NotionAuthError(self._describe(response))
            if response.status_code == 404:
                raise NotionNotFoundError(self._describe(response))
            retryable = response.status_code in (429, 529) or (
                500 <= response.status_code < 600
            )
            if not retryable or attempt == self.max_attempts:
                break
            self._sleep(self._wait_for(response, attempt))
        raise NotionError(
            f"{method} {path} failed with HTTP {last_status} "
            f"after {self.max_attempts} attempts"
        )

    def _wait_for(self, response: httpx.Response, attempt: int) -> float:
        if response.status_code in (429, 529):
            try:
                return float(response.headers.get("Retry-After", BACKOFF_SECONDS))
            except ValueError:
                return BACKOFF_SECONDS
        return BACKOFF_SECONDS * 2 ** (attempt - 1)

    @staticmethod
    def _describe(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = body.get("code", "")
        message = body.get("message", response.text[:200])
        if code == CREDITS_EXHAUSTED_CODE:
            message = (
                "the workspace has no credits left for this endpoint "
                f"({CREDITS_EXHAUSTED_CODE})"
            )
        return f"HTTP {response.status_code} from {response.request.url}: {message}"
