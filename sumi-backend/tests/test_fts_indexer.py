import asyncio
import json

import psycopg
import pytest

from src.retrieval.lexical import PgFtsIndexer


def _postgres_available() -> bool:
    try:
        with psycopg.connect("postgresql://localhost:5432/postgres", connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(), reason="local Postgres is not running"
)

TABLE = "chunks_fts_test"
SOURCE_TABLE = "chunks_dense_test"


@pytest.fixture
def test_db_url() -> str:
    with psycopg.connect(
        "postgresql://localhost:5432/postgres", autocommit=True
    ) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = 'sumi_test'"
        ).fetchone()
        if row is None:
            conn.execute("CREATE DATABASE sumi_test")
    return "postgresql://localhost:5432/sumi_test"


@pytest.fixture
def indexer(test_db_url) -> PgFtsIndexer:
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
        conn.execute(f"DROP TABLE IF EXISTS {SOURCE_TABLE}")
    indexer = PgFtsIndexer(test_db_url, table=TABLE)
    asyncio.run(indexer.ensure_schema())
    return indexer


def insert(indexer: PgFtsIndexer, rows: list[tuple[str, str, str, dict]]) -> None:
    with (
        psycopg.connect(indexer.database_url, autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.executemany(
            f"INSERT INTO {TABLE} (id, text, source, metadata) VALUES (%s, %s, %s, %s)",
            [(i, text, source, json.dumps(meta)) for i, text, source, meta in rows],
        )


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


def test_a_title_hit_outranks_a_body_hit(indexer):
    insert(
        indexer,
        [
            (
                "body#0",
                "a passing mention of kayaking here",
                "b.md",
                {"title": "Other"},
            ),
            ("title#0", "unrelated prose entirely", "t.md", {"title": "Kayaking"}),
        ],
    )
    results = asyncio.run(indexer.search("kayaking"))
    assert [row["id"] for row in results] == ["title#0", "body#0"]


def test_a_rare_term_outweighs_a_repeated_common_one(indexer):
    common = "project " * 20
    insert(
        indexer,
        [(f"common#{i}", f"{common} notes", f"c{i}.md", {}) for i in range(5)]
        + [("rare#0", "kayaking project", "r.md", {})],
    )
    results = asyncio.run(indexer.search("project kayaking"))
    assert results[0]["id"] == "rare#0"


def test_any_query_term_is_enough_to_match(indexer):
    insert(indexer, [("a#0", "notes about kayaking", "a.md", {})])
    results = asyncio.run(indexer.search("what did i write about kayaking in norway?"))
    assert [row["id"] for row in results] == ["a#0"]


def test_terms_in_most_chunks_are_dropped_from_the_query(indexer):
    insert(
        indexer,
        [(f"common#{i}", "a note about work", f"c{i}.md", {}) for i in range(19)]
        + [("rare#0", "a note about kayaking", "r.md", {})],
    )
    results = asyncio.run(indexer.search("work kayaking"))
    assert [row["id"] for row in results] == ["rare#0"]


def test_a_query_of_only_common_terms_still_matches(indexer):
    insert(
        indexer,
        [(f"common#{i}", "a note about work", f"c{i}.md", {}) for i in range(19)],
    )
    assert len(asyncio.run(indexer.search("work"))) == 10


def test_a_stopword_only_query_matches_nothing(indexer):
    insert(indexer, [("a#0", "notes about kayaking", "a.md", {})])
    assert asyncio.run(indexer.search("the of and")) == []


def test_top_k_limits_results(indexer):
    insert(indexer, [(f"a#{i}", "kayaking", f"a{i}.md", {}) for i in range(5)])
    assert len(asyncio.run(indexer.search("kayaking", top_k=2))) == 2


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
