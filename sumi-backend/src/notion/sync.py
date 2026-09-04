"""The sync job: list the workspace, fetch what changed, re-index it, rewrite the mirror.

The job never walks the page tree. It asks Notion's search endpoint for every
page the integration can see, newest edit first, and compares that listing
with what it indexed last time. Only pages that are new or edited cost a
request beyond the listing.

An incremental run stops walking the listing at the **watermark**: the start
time of the last successful run, less ten minutes. The ten minutes absorb
Notion rounding edit times down to the minute and its search index lagging
edits. A full run walks the whole listing, which is the only way to notice a
page that vanished.

State lives in two tables this module creates: `notion_objects`, one row per
page, data source and database, holding the page's normalised text; and
`notion_sync_runs`, one row per run.
"""

import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from src.config import app_config
from src.notion.client import (
    NotionAuthError,
    NotionClient,
    NotionError,
    NotionNotFoundError,
)
from src.notion.markdown import LinkResolver, normalise, render_page
from src.notion.mirror import build_child_dir, build_mirror_path, regenerate_mirror
from src.notion.properties import (
    flatten_properties,
    format_property_lines,
    get_page_title,
    get_plain_text,
)
from src.retrieval.chunker import chunk_text
from src.retrieval.cleaner import clean_text
from src.retrieval.indexer import Document, PgChunkTable
from src.retrieval.retrieve import build_arm_indexer
from src.retrieval.search_config import SYNC_CONFIG, RetrievalConfig

logger = logging.getLogger(__name__)

OBJECTS_TABLE = "notion_objects"
RUNS_TABLE = "notion_sync_runs"
# How far past the last run's start an incremental run keeps walking.
WATERMARK_OVERLAP = timedelta(minutes=10)
PATH_SEPARATOR = " / "


@dataclass(frozen=True)
class NotionObject:
    """A page, data source or database as the listing describes it."""

    id: str
    kind: str
    title: str
    parent_id: str | None
    parent_kind: str
    url: str = ""
    created_time: datetime | None = None
    last_edited_time: datetime | None = None
    in_trash: bool = False
    properties: dict[str, Any] = field(default_factory=dict)
    schema_order: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StoredObject:
    """One `notion_objects` row, without the page text."""

    id: str
    kind: str
    title: str
    parent_id: str | None
    parent_kind: str
    path: str
    mirror_path: str
    last_edited_time: datetime | None
    synced_at: datetime | None


@dataclass(frozen=True)
class Place:
    """Where a page sits: its readable path and its file inside the mirror."""

    path: str
    mirror_path: str
    parent_dir: str


@dataclass(frozen=True)
class RunPlan:
    """What one run will do, worked out from the listing and the stored rows."""

    fetch: tuple[str, ...] = ()
    new: frozenset[str] = frozenset()
    changed: frozenset[str] = frozenset()
    retry: frozenset[str] = frozenset()
    moved: tuple[str, ...] = ()
    current: tuple[str, ...] = ()
    gone: tuple[str, ...] = ()
    listed: int = 0
    stopped_early: bool = False


@dataclass
class SyncReport:
    """The counts one run produces, mirrored in `notion_sync_runs`."""

    mode: str = "incremental"
    status: str = "ok"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    pages_listed: int = 0
    pages_indexed: int = 0
    pages_moved: int = 0
    pages_removed: int = 0
    pages_failed: int = 0
    requests: int = 0
    mirror_files: int = 0
    stopped_early: bool = False
    failed_pages: list[str] = field(default_factory=list)
    dropped_tags: dict[str, int] = field(default_factory=dict)

    def describe(self) -> str:
        early = " (stopped early at the watermark)" if self.stopped_early else ""
        lines = [
            f"{self.mode} sync {self.status}",
            f"  pages listed:  {self.pages_listed}{early}",
            f"  pages indexed: {self.pages_indexed}",
            f"  pages moved:   {self.pages_moved}",
            f"  pages removed: {self.pages_removed}",
            f"  pages failed:  {self.pages_failed}",
            f"  API requests:  {self.requests}",
            f"  mirror files:  {self.mirror_files}",
        ]
        if self.dropped_tags:
            dropped = ", ".join(
                f"{tag} x{count}" for tag, count in sorted(self.dropped_tags.items())
            )
            lines.append(f"  blocks with no export form: {dropped}")
        if self.failed_pages:
            lines.append("  failed page ids: " + ", ".join(self.failed_pages[:10]))
        return "\n".join(lines)


def normalise_id(value: str | None) -> str:
    return (value or "").replace("-", "").lower()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def parse_parent(parent: Mapping[str, Any] | None) -> tuple[str | None, str]:
    """Notion names a parent by type: `{"type": "page_id", "page_id": "..."}`."""
    kind = (parent or {}).get("type", "workspace")
    if not parent or kind == "workspace":
        return None, "workspace"
    return normalise_id(parent.get(kind)), kind.removesuffix("_id")


def parse_object(payload: Mapping[str, Any]) -> NotionObject:
    parent_id, parent_kind = parse_parent(payload.get("parent"))
    kind = payload.get("object", "page")
    properties = payload.get("properties") or {}
    is_page = kind == "page"
    return NotionObject(
        id=normalise_id(payload.get("id")),
        kind=kind,
        title=get_page_title(payload) or get_plain_text(payload.get("name")),
        parent_id=parent_id,
        parent_kind=parent_kind,
        url=payload.get("url") or "",
        created_time=parse_time(payload.get("created_time")),
        last_edited_time=parse_time(payload.get("last_edited_time")),
        in_trash=bool(payload.get("in_trash") or payload.get("archived")),
        properties=properties if is_page else {},
        schema_order=[] if is_page else list(properties),
    )


def to_notion_object(stored: StoredObject) -> NotionObject:
    """A stored row read back, so pages the listing walk never reached still have a place."""
    return NotionObject(
        id=stored.id,
        kind=stored.kind,
        title=stored.title,
        parent_id=stored.parent_id,
        parent_kind=stored.parent_kind,
        last_edited_time=stored.last_edited_time,
    )


def get_effective_parent(
    object_id: str, objects: Mapping[str, NotionObject]
) -> str | None:
    """The parent that shows in a path.

    A database row's parent is a data source, whose parent is the database.
    The two share a title, so the data source level is skipped.
    """
    seen = {object_id}
    parent = objects[object_id].parent_id
    while parent in objects and objects[parent].kind == "data_source":
        if parent in seen:
            return None
        seen.add(parent)
        parent = objects[parent].parent_id
    return parent if parent in objects else None


def compute_places(objects: Mapping[str, NotionObject]) -> dict[str, Place]:
    """Where every object sits, from parent pointers alone — no traversal."""
    parents = {
        object_id: get_effective_parent(object_id, objects) for object_id in objects
    }
    siblings: dict[str | None, list[str]] = {}
    for object_id, parent in parents.items():
        if objects[object_id].kind != "data_source":
            siblings.setdefault(parent, []).append(objects[object_id].title)

    directories: dict[str, str] = {}
    paths: dict[str, str] = {}

    def resolve(object_id: str, seen: frozenset[str]) -> None:
        if object_id in directories:
            return
        parent = parents[object_id]
        if parent is None or parent in seen:
            parent_dir, parent_path = "", ""
        else:
            resolve(parent, seen | {object_id})
            parent_dir, parent_path = directories[parent], paths[parent]
        title = objects[object_id].title
        directories[object_id] = build_child_dir(
            title, object_id, parent_dir, siblings.get(parents[object_id], [])
        )
        paths[object_id] = (
            f"{parent_path}{PATH_SEPARATOR}{title}" if parent_path else title
        )

    for object_id in objects:
        resolve(object_id, frozenset())
    return {
        object_id: Place(
            path=paths[object_id],
            mirror_path=build_mirror_path(
                obj.title,
                object_id,
                directories[parents[object_id]] if parents[object_id] else "",
            )
            if obj.kind == "page"
            else "",
            parent_dir=directories[parents[object_id]] if parents[object_id] else "",
        )
        for object_id, obj in objects.items()
    }


def is_stale(stored: StoredObject) -> bool:
    """True when a page's stored text is older than the edit its row records.

    A page that failed to fetch or normalise keeps its old `synced_at`, so this
    finds it again on the next run even once its edit time has fallen behind
    the watermark and the listing walk no longer reaches it.
    """
    if stored.synced_at is None:
        return True
    return (
        stored.last_edited_time is not None
        and stored.last_edited_time > stored.synced_at
    )


def plan_run(
    listed: Sequence[NotionObject],
    stored: Mapping[str, StoredObject],
    places: Mapping[str, Place],
    full: bool = False,
    reindex: bool = False,
    watermark: datetime | None = None,
    limit: int | None = None,
) -> RunPlan:
    """Sort the listing into new, changed, moved, current and gone."""
    cutoff = (
        None if full or reindex or watermark is None else watermark - WATERMARK_OVERLAP
    )
    seen: set[str] = set()
    fetch: list[str] = []
    new: list[str] = []
    changed: list[str] = []
    moved: list[str] = []
    current: list[str] = []
    gone: list[str] = []
    stopped_early = False

    for page in listed:
        if (
            cutoff is not None
            and page.last_edited_time is not None
            and page.last_edited_time < cutoff
        ):
            stopped_early = True
            break
        seen.add(page.id)
        row = stored.get(page.id)
        if page.in_trash:
            if row is not None:
                gone.append(page.id)
        elif row is None:
            new.append(page.id)
            fetch.append(page.id)
        elif (
            reindex
            or row.synced_at is None
            or row.last_edited_time is None
            or (
                page.last_edited_time is not None
                and page.last_edited_time > row.last_edited_time
            )
        ):
            changed.append(page.id)
            fetch.append(page.id)
        elif (place := places.get(page.id)) is not None and (
            place.mirror_path != row.mirror_path or place.path != row.path
        ):
            moved.append(page.id)
        else:
            current.append(page.id)

    if full:
        gone.extend(
            object_id
            for object_id, row in stored.items()
            if row.kind == "page" and object_id not in seen
        )
    retry = [
        object_id
        for object_id, row in stored.items()
        if row.kind == "page"
        and object_id not in seen
        and object_id not in gone
        and is_stale(row)
    ]
    fetch.extend(retry)

    if limit is not None:
        fetch = fetch[:limit]
        # A limited run is a smoke run against the real workspace. It has not
        # seen the whole listing, so it must never conclude that a page is gone.
        gone = []
    kept = set(fetch)
    return RunPlan(
        fetch=tuple(fetch),
        new=frozenset(page_id for page_id in new if page_id in kept),
        changed=frozenset(page_id for page_id in changed if page_id in kept),
        retry=frozenset(page_id for page_id in retry if page_id in kept),
        moved=tuple(moved),
        current=tuple(current),
        gone=tuple(gone),
        listed=len(seen),
        stopped_early=stopped_early,
    )


def build_chunk_metadata(
    obj: NotionObject, place: Place, titles: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """What every chunk of a page carries. `path` is what read_file accepts."""
    return {
        "title": obj.title,
        "path": place.mirror_path,
        "created_time": obj.created_time.isoformat() if obj.created_time else None,
        "last_edited_time": obj.last_edited_time.isoformat()
        if obj.last_edited_time
        else None,
        "url": obj.url,
        "properties": flatten_properties({"properties": obj.properties}, titles),
    }


def build_documents(
    page_id: str, markdown: str, metadata: Mapping[str, Any]
) -> list[Document]:
    text = clean_text(markdown)
    return [
        Document(
            id=f"{page_id}#{index}", text=chunk, source=page_id, metadata=dict(metadata)
        )
        for index, chunk in enumerate(chunk_text(text) if text else [])
    ]


async def index_page(
    indexers: Sequence[PgChunkTable], page_id: str, documents: Sequence[Document]
) -> int:
    """Upsert a page's chunks in every table, then drop the ones it no longer has."""
    keep = [document.id for document in documents]
    for indexer in indexers:
        await indexer.index(list(documents))
        await indexer.delete_source_except(page_id, keep)
    return len(documents)


async def move_page(
    indexers: Sequence[PgChunkTable], page_id: str, metadata: Mapping[str, Any]
) -> None:
    """A page whose path changed: update its chunks' metadata, embed nothing."""
    for indexer in indexers:
        await indexer.update_metadata(page_id, dict(metadata))


async def remove_page(indexers: Sequence[PgChunkTable], page_id: str) -> None:
    for indexer in indexers:
        await indexer.delete_by_source(page_id)


class SyncStore:
    """The sync's own two tables."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    async def ensure_schema(self) -> None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {} ("
                    "id text PRIMARY KEY, "
                    "kind text NOT NULL, "
                    "title text NOT NULL DEFAULT '', "
                    "parent_id text, "
                    "parent_kind text NOT NULL DEFAULT 'workspace', "
                    "path text NOT NULL DEFAULT '', "
                    "url text NOT NULL DEFAULT '', "
                    "created_time timestamptz, "
                    "last_edited_time timestamptz, "
                    "properties jsonb, "
                    "schema_order jsonb, "
                    "mirror_path text NOT NULL DEFAULT '', "
                    "markdown text, "
                    "chunk_count integer, "
                    "listed_at timestamptz, "
                    "synced_at timestamptz)"
                ).format(sql.Identifier(OBJECTS_TABLE))
            )
            await conn.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {} ("
                    "id bigserial PRIMARY KEY, "
                    "mode text NOT NULL, "
                    "started_at timestamptz NOT NULL, "
                    "finished_at timestamptz, "
                    "status text NOT NULL, "
                    "pages_listed integer NOT NULL DEFAULT 0, "
                    "pages_indexed integer NOT NULL DEFAULT 0, "
                    "pages_moved integer NOT NULL DEFAULT 0, "
                    "pages_removed integer NOT NULL DEFAULT 0, "
                    "pages_failed integer NOT NULL DEFAULT 0, "
                    "requests integer NOT NULL DEFAULT 0)"
                ).format(sql.Identifier(RUNS_TABLE))
            )

    async def load_objects(self) -> dict[str, StoredObject]:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cursor = await conn.execute(
                sql.SQL(
                    "SELECT id, kind, title, parent_id, parent_kind, path, "
                    "mirror_path, last_edited_time, synced_at FROM {}"
                ).format(sql.Identifier(OBJECTS_TABLE))
            )
            rows = await cursor.fetchall()
        return {row[0]: StoredObject(*row) for row in rows}

    async def load_schema_orders(self) -> dict[str, list[str]]:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cursor = await conn.execute(
                sql.SQL(
                    "SELECT id, schema_order FROM {} WHERE schema_order IS NOT NULL"
                ).format(sql.Identifier(OBJECTS_TABLE))
            )
            return {row[0]: row[1] for row in await cursor.fetchall()}

    @staticmethod
    def build_upsert_statement() -> sql.Composed:
        """One row of `notion_objects`; the text columns keep their old values
        when the new ones are NULL, so a listing pass never erases page text."""
        table = sql.Identifier(OBJECTS_TABLE)
        return sql.SQL(
            "INSERT INTO {t} (id, kind, title, parent_id, parent_kind, path, "
            "url, created_time, last_edited_time, properties, schema_order, "
            "mirror_path, markdown, chunk_count, listed_at, synced_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET kind = EXCLUDED.kind, "
            "title = EXCLUDED.title, parent_id = EXCLUDED.parent_id, "
            "parent_kind = EXCLUDED.parent_kind, path = EXCLUDED.path, "
            "url = EXCLUDED.url, created_time = EXCLUDED.created_time, "
            "last_edited_time = EXCLUDED.last_edited_time, "
            "properties = EXCLUDED.properties, "
            "schema_order = EXCLUDED.schema_order, "
            "mirror_path = EXCLUDED.mirror_path, "
            "markdown = COALESCE(EXCLUDED.markdown, {t}.markdown), "
            "chunk_count = COALESCE(EXCLUDED.chunk_count, {t}.chunk_count), "
            "listed_at = COALESCE(EXCLUDED.listed_at, {t}.listed_at), "
            "synced_at = COALESCE(EXCLUDED.synced_at, {t}.synced_at)"
        ).format(t=table)

    @staticmethod
    def build_upsert_values(
        obj: NotionObject,
        place: Place,
        titles: Mapping[str, str] | None = None,
        listed_at: datetime | None = None,
        markdown: str | None = None,
        chunk_count: int | None = None,
        synced_at: datetime | None = None,
    ) -> tuple[Any, ...]:
        return (
            obj.id,
            obj.kind,
            obj.title,
            obj.parent_id,
            obj.parent_kind,
            place.path,
            obj.url,
            obj.created_time,
            obj.last_edited_time,
            Jsonb(flatten_properties({"properties": obj.properties}, titles)),
            Jsonb(obj.schema_order),
            place.mirror_path,
            markdown,
            chunk_count,
            listed_at,
            synced_at,
        )

    async def upsert_object(
        self,
        obj: NotionObject,
        place: Place,
        titles: Mapping[str, str] | None = None,
        listed_at: datetime | None = None,
        markdown: str | None = None,
        chunk_count: int | None = None,
        synced_at: datetime | None = None,
    ) -> None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute(
                self.build_upsert_statement(),
                self.build_upsert_values(
                    obj, place, titles, listed_at, markdown, chunk_count, synced_at
                ),
            )

    async def record_listing(
        self,
        items: Sequence[tuple[NotionObject, Place]],
        titles: Mapping[str, str],
        listed_at: datetime,
    ) -> None:
        """Write a row for everything the listing showed, in one round trip.

        No text and no `synced_at`: a page that failed to fetch still gets a
        row, which is what makes it findable for a retry on the next run even
        once its edit time has fallen below the watermark.
        """
        if not items:
            return
        async with (
            await psycopg.AsyncConnection.connect(self.database_url) as conn,
            conn.cursor() as cur,
        ):
            await cur.executemany(
                self.build_upsert_statement(),
                [
                    self.build_upsert_values(obj, place, titles, listed_at)
                    for obj, place in items
                ],
            )

    async def update_place(self, object_id: str, place: Place) -> None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute(
                sql.SQL(
                    "UPDATE {} SET path = %s, mirror_path = %s WHERE id = %s"
                ).format(sql.Identifier(OBJECTS_TABLE)),
                (place.path, place.mirror_path, object_id),
            )

    async def delete_object(self, object_id: str) -> None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute(
                sql.SQL("DELETE FROM {} WHERE id = %s").format(
                    sql.Identifier(OBJECTS_TABLE)
                ),
                (object_id,),
            )

    async def load_mirror_rows(self) -> list[tuple[str, str]]:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cursor = await conn.execute(
                sql.SQL(
                    "SELECT mirror_path, markdown FROM {} WHERE kind = 'page' "
                    "AND markdown IS NOT NULL AND mirror_path <> '' "
                    "ORDER BY mirror_path"
                ).format(sql.Identifier(OBJECTS_TABLE))
            )
            return [(row[0], row[1]) for row in await cursor.fetchall()]

    async def get_watermark(self) -> datetime | None:
        """When the newest successful run started."""
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cursor = await conn.execute(
                sql.SQL("SELECT max(started_at) FROM {} WHERE status = 'ok'").format(
                    sql.Identifier(RUNS_TABLE)
                )
            )
            row = await cursor.fetchone()
        return row[0] if row else None

    async def start_run(self, mode: str, started_at: datetime) -> int:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cursor = await conn.execute(
                sql.SQL(
                    "INSERT INTO {} (mode, started_at, status) "
                    "VALUES (%s, %s, 'running') RETURNING id"
                ).format(sql.Identifier(RUNS_TABLE)),
                (mode, started_at),
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def finish_run(self, run_id: int, report: SyncReport) -> None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute(
                sql.SQL(
                    "UPDATE {} SET finished_at = %s, status = %s, pages_listed = %s, "
                    "pages_indexed = %s, pages_moved = %s, pages_removed = %s, "
                    "pages_failed = %s, requests = %s WHERE id = %s"
                ).format(sql.Identifier(RUNS_TABLE)),
                (
                    report.finished_at,
                    report.status,
                    report.pages_listed,
                    report.pages_indexed,
                    report.pages_moved,
                    report.pages_removed,
                    report.pages_failed,
                    report.requests,
                    run_id,
                ),
            )


def collect_listing(
    client: NotionClient, cutoff: datetime | None
) -> tuple[list[NotionObject], bool]:
    """Pages newest edit first, stopping at the cutoff so a quiet day is cheap."""
    pages: list[NotionObject] = []
    for payload in client.iter_search("page"):
        page = parse_object(payload)
        if (
            cutoff is not None
            and page.last_edited_time is not None
            and page.last_edited_time < cutoff
        ):
            return pages, True
        pages.append(page)
    return pages, False


def collect_containers(client: NotionClient) -> list[NotionObject]:
    """Every data source the integration can see, plus the databases behind them."""
    containers: list[NotionObject] = []
    database_ids: set[str] = set()
    for payload in client.iter_search("data_source"):
        data_source = parse_object(payload)
        if not data_source.schema_order:
            data_source = parse_object(client.get_data_source(data_source.id))
        containers.append(data_source)
        if data_source.parent_kind == "database" and data_source.parent_id:
            database_ids.add(data_source.parent_id)
    containers.extend(
        parse_object(client.get_database(database_id))
        for database_id in sorted(database_ids)
    )
    return containers


def resolve_block_parents(
    client: NotionClient, objects: dict[str, NotionObject]
) -> None:
    """A page made inside a column or toggle names a block as its parent.

    One lookup per such block finds the page it sits on, so the page still gets
    a path. Results are cached because siblings share the block.
    """
    cache: dict[str, tuple[str | None, str]] = {}
    for object_id, obj in list(objects.items()):
        parent_id, parent_kind = obj.parent_id, obj.parent_kind
        seen: set[str] = set()
        while parent_kind == "block" and parent_id and parent_id not in seen:
            seen.add(parent_id)
            if parent_id not in cache:
                try:
                    cache[parent_id] = parse_parent(
                        client.get_block(parent_id).get("parent")
                    )
                except NotionError:
                    cache[parent_id] = (None, "workspace")
            parent_id, parent_kind = cache[parent_id]
        if (parent_id, parent_kind) != (obj.parent_id, obj.parent_kind):
            objects[object_id] = replace(
                obj, parent_id=parent_id, parent_kind=parent_kind
            )


def build_indexers(config: RetrievalConfig, database_url: str) -> list[Any]:
    """One indexer per arm of the configuration, dense arms and the lexical one."""
    return [build_arm_indexer(arm, database_url) for arm in config.arms]


def build_link_tables(
    objects: Mapping[str, NotionObject], places: Mapping[str, Place]
) -> tuple[dict[str, str], dict[str, str]]:
    """Titles and mirror paths by page id, for rendering links between pages."""
    titles = {object_id: obj.title for object_id, obj in objects.items()}
    mirror_paths = {
        object_id: place.mirror_path
        for object_id, place in places.items()
        if place.mirror_path
    }
    return titles, mirror_paths


async def run_sync(
    mode: str = "incremental",
    reindex: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    mirror_only: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
    client: NotionClient | None = None,
    database_url: str | None = None,
    data_dir: str | Path | None = None,
    config: RetrievalConfig = SYNC_CONFIG,
) -> SyncReport:
    """List, diff, fetch, index, then rewrite the mirror. Safe to interrupt."""
    url = database_url or app_config.database_url
    root = Path(data_dir if data_dir is not None else app_config.data_dir)
    store = SyncStore(url)
    await store.ensure_schema()
    report = SyncReport(mode=mode, started_at=datetime.now(UTC))

    if mirror_only:
        report.mirror_files = regenerate_mirror(await store.load_mirror_rows(), root)
        report.finished_at = datetime.now(UTC)
        return report

    owns_client = client is None
    if client is None:
        if not app_config.notion_token:
            raise RuntimeError(
                "NOTION_TOKEN is empty. Create a read-only Notion integration and "
                "put its secret in .env before running the sync."
            )
        client = NotionClient(app_config.notion_token)

    # A dry run writes nothing, so it needs no tables and no embedding models.
    indexers: list[Any] = []
    if not dry_run:
        indexers = build_indexers(config, url)
        for indexer in indexers:
            await indexer.ensure_schema()

    run_id = 0 if dry_run else await store.start_run(mode, report.started_at)
    try:
        await execute_run(
            client=client,
            store=store,
            indexers=indexers,
            report=report,
            reindex=reindex,
            limit=limit,
            dry_run=dry_run,
            on_progress=on_progress,
            root=root,
        )
    except NotionAuthError:
        report.status = "failed"
        report.finished_at = datetime.now(UTC)
        report.requests = client.request_count
        if not dry_run:
            await store.finish_run(run_id, report)
        raise
    finally:
        if owns_client:
            client.close()

    if not dry_run:
        await store.finish_run(run_id, report)
    return report


async def execute_run(
    client: NotionClient,
    store: SyncStore,
    indexers: Sequence[PgChunkTable],
    report: SyncReport,
    reindex: bool,
    limit: int | None,
    dry_run: bool,
    on_progress: Callable[[int, int], None] | None,
    root: Path,
) -> None:
    """One run's work, on a report it fills in as it goes."""
    full = report.mode == "full"
    started_at = report.started_at or datetime.now(UTC)
    stored = await store.load_objects()
    watermark = None if full else await store.get_watermark()
    cutoff = (
        None if full or reindex or watermark is None else watermark - WATERMARK_OVERLAP
    )

    containers = collect_containers(client)
    listed, stopped_early = collect_listing(client, cutoff)
    objects: dict[str, NotionObject] = {
        object_id: to_notion_object(row) for object_id, row in stored.items()
    }
    for obj in [*containers, *listed]:
        objects[obj.id] = obj
    resolve_block_parents(client, objects)
    places = compute_places(objects)

    plan = plan_run(
        listed,
        stored,
        places,
        full=full,
        reindex=reindex,
        watermark=watermark,
        limit=limit,
    )
    report.pages_listed = plan.listed
    report.stopped_early = stopped_early or plan.stopped_early
    report.requests = client.request_count
    if dry_run:
        report.pages_indexed = len(plan.fetch)
        report.pages_moved = len(plan.moved)
        report.pages_removed = len(plan.gone)
        report.finished_at = datetime.now(UTC)
        return

    schema_orders = {obj.id: obj.schema_order for obj in containers}
    schema_orders.update(await store.load_schema_orders())
    titles, mirror_paths = build_link_tables(objects, places)

    listed_ids = {page.id for page in listed}
    removed: set[str] = set()
    dropped: Counter[str] = Counter()
    for done, page_id in enumerate(plan.fetch, start=1):
        try:
            if page_id not in listed_ids:
                objects[page_id] = parse_object(client.get_page(page_id))
                places = compute_places(objects)
                titles, mirror_paths = build_link_tables(objects, places)
            await sync_one_page(
                client=client,
                store=store,
                indexers=indexers,
                obj=objects[page_id],
                place=places[page_id],
                schema_orders=schema_orders,
                titles=titles,
                mirror_paths=mirror_paths,
                dropped=dropped,
                listed_at=started_at,
            )
            report.pages_indexed += 1
        except NotionAuthError:
            raise
        except NotionNotFoundError:
            await remove_page(indexers, page_id)
            await store.delete_object(page_id)
            removed.add(page_id)
            report.pages_removed += 1
        except (NotionError, OSError, ValueError, KeyError) as error:
            logger.warning("page %s failed: %s", page_id, error)
            report.pages_failed += 1
            report.failed_pages.append(page_id)
        if on_progress is not None:
            on_progress(done, len(plan.fetch))

    for page_id in plan.gone:
        await remove_page(indexers, page_id)
        await store.delete_object(page_id)
        removed.add(page_id)
        report.pages_removed += 1

    # Moves run before the listing is recorded: recording writes the new path,
    # which would otherwise hide the difference this pass looks for.
    report.pages_moved = await reconcile_places(
        store, indexers, await store.load_objects(), places
    )
    await store.record_listing(
        [
            (obj, places[obj.id])
            for obj in [*containers, *listed]
            if obj.id not in removed and not obj.in_trash
        ],
        titles,
        started_at,
    )
    report.mirror_files = regenerate_mirror(await store.load_mirror_rows(), root)
    report.dropped_tags = dict(dropped)
    report.requests = client.request_count
    report.finished_at = datetime.now(UTC)


def render_synced_page(
    enhanced: str,
    obj: NotionObject,
    place: Place,
    schema_orders: Mapping[str, list[str]],
    titles: Mapping[str, str],
    mirror_paths: Mapping[str, str],
    dropped: Counter[str] | None = None,
) -> str:
    """Notion's markdown for one page, rendered in the export's shape.

    The fidelity check calls this too, so what it measures is exactly what the
    sync stores.
    """
    links = LinkResolver(
        mirror_paths=mirror_paths, titles=titles, base_dir=place.parent_dir
    )
    body = normalise(enhanced, links, dropped)
    property_lines = format_property_lines(
        obj.properties, schema_orders.get(obj.parent_id or "", []), titles
    )
    return render_page({"properties": obj.properties}, body, property_lines)


async def sync_one_page(
    client: NotionClient,
    store: SyncStore,
    indexers: Sequence[PgChunkTable],
    obj: NotionObject,
    place: Place,
    schema_orders: Mapping[str, list[str]],
    titles: Mapping[str, str],
    mirror_paths: Mapping[str, str],
    dropped: Counter[str],
    listed_at: datetime,
) -> None:
    """Fetch one page, normalise it, replace its chunks, record its row."""
    counted: Counter[str] = Counter()
    markdown = render_synced_page(
        client.get_page_markdown(obj.id),
        obj,
        place,
        schema_orders,
        titles,
        mirror_paths,
        counted,
    )
    metadata = build_chunk_metadata(obj, place, titles)
    documents = build_documents(obj.id, markdown, metadata)
    chunk_count = await index_page(indexers, obj.id, documents)
    await store.upsert_object(
        obj,
        place,
        titles=titles,
        listed_at=listed_at,
        markdown=markdown,
        chunk_count=chunk_count,
        synced_at=datetime.now(UTC),
    )
    dropped.update(counted)


async def reconcile_places(
    store: SyncStore,
    indexers: Sequence[PgChunkTable],
    stored: Mapping[str, StoredObject],
    places: Mapping[str, Place],
) -> int:
    """Move every page whose path changed, a renamed page's children included.

    Renaming a parent does not bump a child's last edited time, so an
    incremental run never lists the children. Comparing each stored path with
    the one the fresh tree implies catches them anyway, and a move costs one
    UPDATE per table — no fetch and no embedding.
    """
    moved = 0
    for object_id, row in stored.items():
        place = places.get(object_id)
        if place is None or row.kind != "page":
            continue
        if place.path == row.path and place.mirror_path == row.mirror_path:
            continue
        await move_page(indexers, object_id, {"path": place.mirror_path})
        await store.update_place(object_id, place)
        moved += 1
    return moved


def describe_index_staleness(database_url: str | None = None) -> str | None:
    """One line for the REPL: how old the index is, or None when nothing has synced."""
    url = database_url or app_config.database_url
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            latest = conn.execute(
                sql.SQL(
                    "SELECT mode, started_at FROM {} WHERE status = 'ok' "
                    "ORDER BY started_at DESC LIMIT 1"
                ).format(sql.Identifier(RUNS_TABLE))
            ).fetchone()
            if latest is None:
                return None
            full = conn.execute(
                sql.SQL(
                    "SELECT max(started_at) FROM {} WHERE status = 'ok' "
                    "AND mode = 'full'"
                ).format(sql.Identifier(RUNS_TABLE))
            ).fetchone()
    except psycopg.Error:
        return None
    line = f"notes index: last synced {format_age(latest[1])} ago ({latest[0]})"
    if full and full[0]:
        line += f", last full listing {format_age(full[0])} ago"
    return line


def format_age(moment: datetime) -> str:
    seconds = (datetime.now(UTC) - moment).total_seconds()
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{int(seconds // 60)} min"
    if seconds < 172800:
        return f"{int(seconds // 3600)} h"
    return f"{int(seconds // 86400)} days"
