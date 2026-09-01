import asyncio
import json

import psycopg
import pytest

from src.retrieval.lexical import PgFtsIndexer

pytestmark = pytest.mark.postgres

TABLE = "chunks_fts_test"
SOURCE_TABLE = "chunks_dense_test"

Row = tuple[str, str, str, dict]


@pytest.fixture
def indexer(test_db_url) -> PgFtsIndexer:
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
        conn.execute(f"DROP TABLE IF EXISTS {SOURCE_TABLE}")
    indexer = PgFtsIndexer(test_db_url, table=TABLE)
    asyncio.run(indexer.ensure_schema())
    return indexer


def insert(indexer: PgFtsIndexer, rows: list[Row]) -> None:
    with (
        psycopg.connect(indexer.database_url, autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.executemany(
            f"INSERT INTO {TABLE} (id, text, source, metadata) VALUES (%s, %s, %s, %s)",
            [(i, text, source, json.dumps(meta)) for i, text, source, meta in rows],
        )


def make_rows(count: int, text: str) -> list[Row]:
    return [(f"common#{i}", text, f"c{i}.md", {}) for i in range(count)]


def test_ensure_schema_is_idempotent(indexer):
    asyncio.run(indexer.ensure_schema())


def test_search_returns_the_indexer_row_shape(indexer):
    insert(indexer, [("a#0", "notes about kayaking", "a.md", {"title": "Kayaks"})])
    [row] = asyncio.run(indexer.search("kayaking"))
    assert row["id"] == "a#0"
    assert row["text"] == "notes about kayaking"
    assert row["source"] == "a.md"
    assert row["metadata"] == {"title": "Kayaks"}
    assert row["score"] > 0


@pytest.mark.parametrize(
    ("rows", "query", "expected_ids"),
    [
        (
            [
                ("body#0", "a passing mention of kayaking", "b.md", {"title": "Other"}),
                ("title#0", "unrelated prose entirely", "t.md", {"title": "Kayaking"}),
            ],
            "kayaking",
            ["title#0", "body#0"],
        ),
        (
            make_rows(5, "project " * 20 + "notes")
            + [("rare#0", "kayaking project", "r.md", {})],
            "project kayaking",
            ["rare#0", "common#0", "common#1", "common#2", "common#3", "common#4"],
        ),
        (
            [("a#0", "notes about kayaking", "a.md", {})],
            "what did i write about kayaking in norway?",
            ["a#0"],
        ),
        (
            make_rows(19, "a note about work")
            + [("rare#0", "a note about kayaking", "r.md", {})],
            "work kayaking",
            ["rare#0"],
        ),
        ([("a#0", "notes about kayaking", "a.md", {})], "the of and", []),
    ],
    ids=[
        "title-hit-outranks-body-hit",
        "rare-term-outweighs-repeated-common-one",
        "any-query-term-matches",
        "terms-above-max_df-dropped",
        "stopwords-only-match-nothing",
    ],
)
def test_search_ranking(indexer, rows, query, expected_ids):
    insert(indexer, rows)
    assert [row["id"] for row in asyncio.run(indexer.search(query))] == expected_ids


@pytest.mark.parametrize(
    ("count", "top_k", "expected"),
    [(19, None, 10), (5, 2, 2)],
    ids=["all-terms-above-max_df-still-match", "top-k-limits-results"],
)
def test_search_result_count(indexer, count, top_k, expected):
    insert(indexer, make_rows(count, "a note about work"))
    assert len(asyncio.run(indexer.search("work", top_k=top_k))) == expected


def test_sync_from_copies_and_upserts(indexer):
    with psycopg.connect(indexer.database_url, autocommit=True) as conn:
        conn.execute(
            f"CREATE TABLE {SOURCE_TABLE} (id text PRIMARY KEY, text text, "
            "source text, metadata jsonb)"
        )
        conn.execute(
            f"INSERT INTO {SOURCE_TABLE} VALUES ('a#0', 'kayaking', 'a.md', '{{}}')"
        )
    assert asyncio.run(indexer.sync_from(SOURCE_TABLE)) == 1

    with psycopg.connect(indexer.database_url, autocommit=True) as conn:
        conn.execute(f"UPDATE {SOURCE_TABLE} SET text = 'canoeing'")
    asyncio.run(indexer.sync_from(SOURCE_TABLE))

    assert asyncio.run(indexer.search("canoeing"))[0]["text"] == "canoeing"
    assert asyncio.run(indexer.search("kayaking")) == []


def test_index_is_not_supported(indexer):
    with pytest.raises(NotImplementedError):
        indexer.index([])
