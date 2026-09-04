import json

import httpx
import pytest

from src.notion.client import (
    NOTION_VERSION,
    NotionAuthError,
    NotionClient,
    NotionError,
    NotionNotFoundError,
    TokenBucket,
)


class FakeClock:
    """A monotonic clock that only moves when something sleeps on it."""

    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def build_client(handler, clock: FakeClock | None = None, **kwargs) -> NotionClient:
    clock = clock or FakeClock()
    return NotionClient(
        "secret",
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        **kwargs,
    )


def test_token_bucket_spaces_requests_beyond_its_burst():
    clock = FakeClock()
    bucket = TokenBucket(3.0, monotonic=clock.monotonic, sleep=clock.sleep)

    for _ in range(5):
        bucket.acquire()

    assert clock.slept == pytest.approx([1 / 3, 1 / 3])


def test_iter_search_follows_the_next_cursor():
    seen_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_bodies.append(json.loads(request.content))
        if len(seen_bodies) == 1:
            return httpx.Response(
                200,
                json={
                    "results": [{"id": "a"}],
                    "has_more": True,
                    "next_cursor": "cur-1",
                },
            )
        return httpx.Response(
            200, json={"results": [{"id": "b"}], "has_more": False, "next_cursor": None}
        )

    client = build_client(handler)

    assert [page["id"] for page in client.iter_search()] == ["a", "b"]
    assert "start_cursor" not in seen_bodies[0]
    assert seen_bodies[1]["start_cursor"] == "cur-1"
    assert seen_bodies[0]["filter"] == {"property": "object", "value": "page"}
    assert seen_bodies[0]["sort"]["direction"] == "descending"
    assert client.request_count == 2


def test_iter_search_takes_the_object_kind():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["filter"]["value"] == "data_source"
        return httpx.Response(200, json={"results": [], "has_more": False})

    assert list(build_client(handler).iter_search("data_source")) == []


def test_every_request_sends_the_version_and_token_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"markdown": "# A", "truncated": False})

    build_client(handler).get_page_markdown("page-1")

    assert seen["notion-version"] == NOTION_VERSION
    assert seen["authorization"] == "Bearer secret"


def test_get_page_markdown_returns_the_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/pages/page-1/markdown")
        return httpx.Response(200, json={"markdown": "# A\n\nbody", "truncated": False})

    assert build_client(handler).get_page_markdown("page-1") == "# A\n\nbody"


def test_truncated_page_appends_its_unknown_blocks():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pages/page-1/markdown"):
            return httpx.Response(
                200,
                json={
                    "markdown": "start",
                    "truncated": True,
                    "unknown_block_ids": ["b1", "b2"],
                },
            )
        block_id = request.url.path.split("/")[-2]
        return httpx.Response(200, json={"markdown": f"rest of {block_id}"})

    client = build_client(handler)

    assert client.get_page_markdown("page-1") == "start\nrest of b1\nrest of b2"
    assert client.request_count == 3


def test_rate_limit_sleeps_for_retry_after_then_retries():
    clock = FakeClock()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={})
        return httpx.Response(200, json={"markdown": "ok"})

    client = build_client(handler, clock=clock)

    assert client.get_page_markdown("page-1") == "ok"
    assert 7.0 in clock.slept
    assert client.request_count == 2


def test_server_error_backs_off_exponentially_then_gives_up():
    clock = FakeClock()
    client = build_client(
        lambda request: httpx.Response(500, json={}), clock=clock, max_attempts=3
    )

    with pytest.raises(NotionError, match="HTTP 500"):
        client.get_page_markdown("page-1")

    assert clock.slept == [1.0, 2.0]
    assert client.request_count == 3


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_stop_the_run_without_retrying(status):
    clock = FakeClock()
    client = build_client(lambda request: httpx.Response(status, json={}), clock=clock)

    with pytest.raises(NotionAuthError):
        client.get_page_markdown("page-1")

    assert client.request_count == 1
    assert clock.slept == []


def test_exhausted_credits_are_named_in_the_error():
    client = build_client(
        lambda request: httpx.Response(
            403, json={"code": "workspace_credits_exhausted", "message": "no"}
        )
    )

    with pytest.raises(NotionAuthError, match="workspace_credits_exhausted"):
        client.get_page_markdown("page-1")


def test_missing_page_raises_not_found():
    client = build_client(lambda request: httpx.Response(404, json={"message": "gone"}))

    with pytest.raises(NotionNotFoundError):
        client.get_page_markdown("page-1")


@pytest.mark.parametrize(
    ("method", "argument", "expected_path"),
    [
        ("get_page", "p1", "/v1/pages/p1"),
        ("get_data_source", "d1", "/v1/data_sources/d1"),
        ("get_database", "db1", "/v1/databases/db1"),
        ("get_block", "b1", "/v1/blocks/b1"),
    ],
)
def test_lookups_hit_their_endpoint(method, argument, expected_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"id": argument})

    client = build_client(handler)

    assert getattr(client, method)(argument) == {"id": argument}
    assert seen == [expected_path]


def test_an_empty_token_is_refused():
    with pytest.raises(ValueError):
        NotionClient("")
