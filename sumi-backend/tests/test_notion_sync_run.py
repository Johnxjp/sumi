"""A whole sync run against a fake Notion workspace and a local Postgres.

The Notion side is an httpx.MockTransport, so nothing reaches the network. The
retrieval side is the lexical arm alone, which stores text without embedding
anything, so no model is loaded.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest

from src.notion.client import NotionClient
from src.notion.sync import OBJECTS_TABLE, RUNS_TABLE, SyncStore, run_sync
from src.retrieval.search_config import ArmConfig, RetrievalConfig

pytestmark = pytest.mark.postgres

FTS_TABLE = "chunks_fts_sync_test"
CONFIG = RetrievalConfig(
    arms=(ArmConfig(name="fts", kind="lexical", table=FTS_TABLE),), fusion="single"
)
# Relative to the wall clock, because the watermark an incremental run compares
# against is the previous run's start time.
NOW = datetime.now(UTC)
LIFE_OS = "1" * 32
CAREER = "2" * 32
JOURNAL_DB = "3" * 32
JOURNAL_DS = "4" * 32
CARING = "5" * 32


def build_page(
    page_id: str,
    title: str,
    parent: dict[str, Any],
    edited: datetime = NOW,
    in_trash: bool = False,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "object": "page",
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "created_time": "2026-01-01T00:00:00.000Z",
        "last_edited_time": edited.isoformat().replace("+00:00", "Z"),
        "in_trash": in_trash,
        "parent": parent,
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": title}]},
            **(properties or {}),
        },
    }


class FakeWorkspace:
    """Serves the five endpoints the sync calls, from dictionaries."""

    def __init__(self):
        self.pages: dict[str, dict[str, Any]] = {}
        self.markdown: dict[str, str] = {}
        self.data_sources: dict[str, dict[str, Any]] = {}
        self.databases: dict[str, dict[str, Any]] = {}
        self.failing: set[str] = set()
        self.markdown_requests: list[str] = []

    def add_page(self, page: dict[str, Any], markdown: str) -> None:
        self.pages[page["id"]] = page
        self.markdown[page["id"]] = markdown

    def add_journal(self) -> None:
        self.databases[JOURNAL_DB] = {
            "object": "database",
            "id": JOURNAL_DB,
            "title": [{"plain_text": "Journal"}],
            "parent": {"type": "page_id", "page_id": LIFE_OS},
        }
        self.data_sources[JOURNAL_DS] = {
            "object": "data_source",
            "id": JOURNAL_DS,
            "title": [{"plain_text": "Journal"}],
            "parent": {"type": "database_id", "database_id": JOURNAL_DB},
            "properties": {"Name": {}, "Created": {}, "Tags": {}},
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/search":
            return self._search(json.loads(request.content))
        if path.endswith("/markdown"):
            page_id = path.split("/")[-2]
            self.markdown_requests.append(page_id)
            if page_id in self.failing:
                return httpx.Response(500, json={})
            return httpx.Response(
                200,
                json={"markdown": self.markdown.get(page_id, ""), "truncated": False},
            )
        object_id = path.split("/")[-1]
        for store in (self.pages, self.data_sources, self.databases):
            if object_id in store:
                return httpx.Response(200, json=store[object_id])
        return httpx.Response(404, json={"message": "not found"})

    def _search(self, body: dict[str, Any]) -> httpx.Response:
        kind = body["filter"]["value"]
        source = self.pages if kind == "page" else self.data_sources
        results = sorted(
            source.values(),
            key=lambda item: item.get("last_edited_time", ""),
            reverse=True,
        )
        return httpx.Response(
            200, json={"results": results, "has_more": False, "next_cursor": None}
        )


@pytest.fixture
def workspace() -> FakeWorkspace:
    space = FakeWorkspace()
    space.add_journal()
    space.add_page(
        build_page(LIFE_OS, "Life OS", {"type": "workspace", "workspace": True}),
        "The root of everything.",
    )
    space.add_page(
        build_page(CAREER, "Career", {"type": "page_id", "page_id": LIFE_OS}),
        "Notes on work and kayaking.",
    )
    space.add_page(
        build_page(
            CARING,
            "Caring",
            {"type": "data_source_id", "data_source_id": JOURNAL_DS},
            properties={
                "Created": {
                    "type": "created_time",
                    "created_time": "2026-05-28T02:23:00.000Z",
                },
                "Tags": {"type": "multi_select", "multi_select": [{"name": "Daily"}]},
            },
        ),
        "> You tend to over-theorize and under-ship",
    )
    return space


@pytest.fixture
def clean_db(test_db_url) -> str:
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        for table in (FTS_TABLE, OBJECTS_TABLE, RUNS_TABLE):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    return test_db_url


def sync(workspace: FakeWorkspace, db_url: str, mirror, **kwargs):
    client = NotionClient(
        "secret", transport=httpx.MockTransport(workspace.handle), sleep=lambda s: None
    )
    try:
        return asyncio.run(
            run_sync(
                client=client,
                database_url=db_url,
                data_dir=mirror,
                config=CONFIG,
                **kwargs,
            )
        )
    finally:
        client.close()


def read_objects(db_url: str) -> dict[str, tuple]:
    with psycopg.connect(db_url) as conn:
        rows = conn.execute(
            f"SELECT id, title, path, mirror_path, chunk_count, synced_at "
            f"FROM {OBJECTS_TABLE}"
        ).fetchall()
    return {row[0]: row[1:] for row in rows}


def read_chunks(db_url: str) -> dict[str, tuple[str, dict]]:
    with psycopg.connect(db_url) as conn:
        rows = conn.execute(
            f"SELECT id, source, metadata FROM {FTS_TABLE} ORDER BY id"
        ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def test_a_full_run_indexes_every_page(workspace, clean_db, tmp_path):
    report = sync(workspace, clean_db, tmp_path / "mirror", mode="full")

    assert report.status == "ok"
    assert report.pages_listed == 3
    assert report.pages_indexed == 3
    assert report.pages_failed == 0
    chunks = read_chunks(clean_db)
    assert {source for source, _ in chunks.values()} == {LIFE_OS, CAREER, CARING}


def test_a_full_run_writes_the_mirror_with_the_export_layout(
    workspace, clean_db, tmp_path
):
    mirror = tmp_path / "mirror"

    report = sync(workspace, clean_db, mirror, mode="full")

    assert report.mirror_files == 3
    caring = mirror / "Life OS" / "Journal" / f"Caring {CARING}.md"
    assert caring.read_text() == (
        "# Caring\n\nCreated: May 28, 2026 3:23 AM\nTags: Daily\n\n"
        "> You tend to over-theorize and under-ship\n> \n"
    )
    assert (mirror / "Life OS" / f"Career {CAREER}.md").exists()


def test_chunks_carry_the_path_read_file_takes(workspace, clean_db, tmp_path):
    sync(workspace, clean_db, tmp_path / "mirror", mode="full")

    _, metadata = read_chunks(clean_db)[f"{CARING}#0"]
    assert metadata["title"] == "Caring"
    assert metadata["path"] == f"Life OS/Journal/Caring {CARING}.md"
    assert metadata["properties"] == {
        "Created": "2026-05-28T02:23:00.000Z",
        "Tags": "Daily",
    }
    assert metadata["url"] == f"https://notion.so/{CARING}"


def test_the_state_table_records_every_object(workspace, clean_db, tmp_path):
    sync(workspace, clean_db, tmp_path / "mirror", mode="full")

    objects = read_objects(clean_db)
    assert set(objects) == {LIFE_OS, CAREER, CARING, JOURNAL_DS, JOURNAL_DB}
    assert objects[CARING][1] == "Life OS / Journal / Caring"
    assert objects[CARING][3] == 1
    assert objects[CARING][4] is not None


def test_a_second_run_fetches_nothing_when_nothing_changed(
    workspace, clean_db, tmp_path
):
    mirror = tmp_path / "mirror"
    sync(workspace, clean_db, mirror, mode="full")
    workspace.markdown_requests.clear()

    report = sync(workspace, clean_db, mirror)

    assert workspace.markdown_requests == []
    assert report.pages_indexed == 0


def test_an_edited_page_is_reindexed_by_an_incremental_run(
    workspace, clean_db, tmp_path
):
    mirror = tmp_path / "mirror"
    sync(workspace, clean_db, mirror, mode="full")
    workspace.pages[CAREER]["last_edited_time"] = (
        (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    )
    workspace.markdown[CAREER] = "Now about canoeing instead."

    report = sync(workspace, clean_db, mirror)

    assert report.pages_indexed == 1
    assert workspace.markdown_requests[-1] == CAREER
    assert "canoeing" in (mirror / "Life OS" / f"Career {CAREER}.md").read_text()


def test_an_incremental_run_stops_at_the_watermark(workspace, clean_db, tmp_path):
    mirror = tmp_path / "mirror"
    sync(workspace, clean_db, mirror, mode="full")
    for page in workspace.pages.values():
        page["last_edited_time"] = "2020-01-01T00:00:00.000Z"

    report = sync(workspace, clean_db, mirror)

    assert report.stopped_early is True
    assert report.pages_listed == 0


def test_a_trashed_page_is_removed_by_a_full_run(workspace, clean_db, tmp_path):
    mirror = tmp_path / "mirror"
    sync(workspace, clean_db, mirror, mode="full")
    workspace.pages[CAREER]["in_trash"] = True

    report = sync(workspace, clean_db, mirror, mode="full")

    assert report.pages_removed == 1
    assert CAREER not in read_objects(clean_db)
    assert not (mirror / "Life OS" / f"Career {CAREER}.md").exists()
    assert all(source != CAREER for source, _ in read_chunks(clean_db).values())


def test_a_page_that_vanished_from_the_listing_is_removed_by_a_full_run(
    workspace, clean_db, tmp_path
):
    mirror = tmp_path / "mirror"
    sync(workspace, clean_db, mirror, mode="full")
    del workspace.pages[CAREER]

    report = sync(workspace, clean_db, mirror, mode="full")

    assert report.pages_removed == 1
    assert CAREER not in read_objects(clean_db)


def test_renaming_a_parent_moves_its_children_without_refetching_them(
    workspace, clean_db, tmp_path
):
    mirror = tmp_path / "mirror"
    sync(workspace, clean_db, mirror, mode="full")
    workspace.pages[LIFE_OS]["properties"]["Name"]["title"] = [{"plain_text": "Life"}]
    workspace.pages[LIFE_OS]["last_edited_time"] = (
        (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    )
    workspace.markdown_requests.clear()

    report = sync(workspace, clean_db, mirror)

    assert workspace.markdown_requests == [LIFE_OS]
    assert report.pages_moved == 2
    assert read_objects(clean_db)[CARING][1] == "Life / Journal / Caring"
    _, metadata = read_chunks(clean_db)[f"{CARING}#0"]
    assert metadata["path"] == f"Life/Journal/Caring {CARING}.md"
    assert (mirror / "Life" / "Journal" / f"Caring {CARING}.md").exists()


def test_a_failed_page_is_counted_and_retried_on_the_next_run(
    workspace, clean_db, tmp_path
):
    mirror = tmp_path / "mirror"
    workspace.failing = {CAREER}

    first = sync(workspace, clean_db, mirror, mode="full")

    assert first.pages_failed == 1
    assert first.failed_pages == [CAREER]
    assert read_objects(clean_db)[CAREER][4] is None

    workspace.failing = set()
    workspace.markdown_requests.clear()
    second = sync(workspace, clean_db, mirror)

    assert workspace.markdown_requests == [CAREER]
    assert second.pages_indexed == 1
    assert read_objects(clean_db)[CAREER][4] is not None


def test_a_limited_run_indexes_at_most_n_pages(workspace, clean_db, tmp_path):
    report = sync(workspace, clean_db, tmp_path / "mirror", mode="full", limit=2)

    assert report.pages_indexed == 2
    assert len(workspace.markdown_requests) == 2


def test_a_dry_run_writes_nothing(workspace, clean_db, tmp_path):
    mirror = tmp_path / "mirror"

    report = sync(workspace, clean_db, mirror, mode="full", dry_run=True)

    assert report.pages_indexed == 3
    assert workspace.markdown_requests == []
    assert read_objects(clean_db) == {}
    assert not mirror.exists()


def test_mirror_only_rebuilds_the_folder_without_the_network(
    workspace, clean_db, tmp_path
):
    mirror = tmp_path / "mirror"
    sync(workspace, clean_db, mirror, mode="full")
    (mirror / "Life OS" / f"Career {CAREER}.md").unlink()
    workspace.markdown_requests.clear()

    report = sync(workspace, clean_db, mirror, mirror_only=True)

    assert report.mirror_files == 3
    assert workspace.markdown_requests == []
    assert (mirror / "Life OS" / f"Career {CAREER}.md").exists()


def test_a_run_is_recorded_in_the_runs_table(workspace, clean_db, tmp_path):
    sync(workspace, clean_db, tmp_path / "mirror", mode="full")

    with psycopg.connect(clean_db) as conn:
        [row] = conn.execute(
            f"SELECT mode, status, pages_listed, pages_indexed, requests "
            f"FROM {RUNS_TABLE}"
        ).fetchall()
    assert row == ("full", "ok", 3, 3, 6)


def test_the_watermark_is_the_last_successful_run(workspace, clean_db, tmp_path):
    sync(workspace, clean_db, tmp_path / "mirror", mode="full")

    watermark = asyncio.run(SyncStore(clean_db).get_watermark())

    assert watermark is not None


def test_ensure_schema_is_idempotent(clean_db):
    store = SyncStore(clean_db)
    asyncio.run(store.ensure_schema())
    asyncio.run(store.ensure_schema())

    assert asyncio.run(store.load_objects()) == {}
