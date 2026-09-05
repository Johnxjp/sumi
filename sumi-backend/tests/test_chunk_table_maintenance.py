"""Row maintenance the Notion sync needs from every chunk table."""

import asyncio
import json

import psycopg
import pytest

from src.retrieval.indexer import Document, PgVectorIndexer
from src.retrieval.lexical import PgFtsIndexer

pytestmark = pytest.mark.postgres

DENSE_TABLE = "chunks_maintenance_test"
FTS_TABLE = "chunks_fts_maintenance_test"
PAGE = "336d52d026fc8076ade8f7b2612f1fef"
OTHER_PAGE = "146d52d026fc8065a351fc6e2ea53f8b"


class FakeEmbedder:
    """One fixed vector per text, so nothing loads a model."""

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    async def embed_documents(self, texts, titles=None):
        return [self.vectors[text] for text in texts]

    async def embed_query(self, text):
        return self.vectors[text]


def make_document(chunk_id: str, text: str, source: str = PAGE) -> Document:
    return Document(
        id=chunk_id, text=text, source=source, metadata={"title": "T", "path": "old.md"}
    )


@pytest.fixture
def dense(test_db_url) -> PgVectorIndexer:
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {DENSE_TABLE}")
    vectors = {f"chunk {i}": [1.0, i / 10, 0.0] for i in range(6)}
    indexer = PgVectorIndexer(
        test_db_url, embedder=FakeEmbedder(vectors), dimensions=3, table=DENSE_TABLE
    )
    asyncio.run(indexer.ensure_schema())
    return indexer


@pytest.fixture
def fts(test_db_url) -> PgFtsIndexer:
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {FTS_TABLE}")
    indexer = PgFtsIndexer(test_db_url, table=FTS_TABLE)
    asyncio.run(indexer.ensure_schema())
    return indexer


def read_rows(database_url: str, table: str) -> list[tuple]:
    with psycopg.connect(database_url) as conn:
        return conn.execute(
            f"SELECT id, source, metadata FROM {table} ORDER BY id"
        ).fetchall()


def index_page(indexer, chunk_ids: list[str], source: str = PAGE) -> None:
    asyncio.run(
        indexer.index(
            [make_document(f"{source}#{i}", f"chunk {i}", source) for i in chunk_ids]
        )
    )


@pytest.mark.parametrize("arm", ["dense", "fts"])
@pytest.mark.parametrize(
    ("first", "second"),
    [([0, 1, 2], [0, 1]), ([0], [0, 1, 2]), ([0, 1], [0, 1])],
    ids=["a-page-that-shrank", "a-page-that-grew", "a-page-that-stayed-the-same"],
)
def test_upsert_then_trim_leaves_exactly_the_new_chunks(request, arm, first, second):
    indexer = request.getfixturevalue(arm)
    index_page(indexer, first)

    index_page(indexer, second)
    keep = [f"{PAGE}#{i}" for i in second]
    asyncio.run(indexer.delete_source_except(PAGE, keep))

    assert [row[0] for row in read_rows(indexer.database_url, indexer.table)] == keep


@pytest.mark.parametrize("arm", ["dense", "fts"])
def test_trimming_one_page_leaves_other_pages_alone(request, arm):
    indexer = request.getfixturevalue(arm)
    index_page(indexer, [0, 1])
    index_page(indexer, [0], source=OTHER_PAGE)

    asyncio.run(indexer.delete_source_except(PAGE, [f"{PAGE}#0"]))

    assert [row[0] for row in read_rows(indexer.database_url, indexer.table)] == [
        f"{OTHER_PAGE}#0",
        f"{PAGE}#0",
    ]


@pytest.mark.parametrize("arm", ["dense", "fts"])
def test_delete_by_source_removes_a_whole_page(request, arm):
    indexer = request.getfixturevalue(arm)
    index_page(indexer, [0, 1])
    index_page(indexer, [0], source=OTHER_PAGE)

    assert asyncio.run(indexer.delete_by_source(PAGE)) == 2
    assert [row[1] for row in read_rows(indexer.database_url, indexer.table)] == [
        OTHER_PAGE
    ]


@pytest.mark.parametrize("arm", ["dense", "fts"])
def test_update_metadata_merges_keys_into_every_chunk_of_a_page(request, arm):
    indexer = request.getfixturevalue(arm)
    index_page(indexer, [0, 1])
    index_page(indexer, [0], source=OTHER_PAGE)

    updated = asyncio.run(
        indexer.update_metadata(PAGE, {"path": "Life OS/new.md", "title": "Renamed"})
    )

    assert updated == 2
    rows = {row[0]: row[2] for row in read_rows(indexer.database_url, indexer.table)}
    assert rows[f"{PAGE}#0"] == {"title": "Renamed", "path": "Life OS/new.md"}
    assert rows[f"{OTHER_PAGE}#0"] == {"title": "T", "path": "old.md"}


def test_a_moved_page_keeps_its_text_and_embedding(dense):
    index_page(dense, [0])
    with psycopg.connect(dense.database_url) as conn:
        before = conn.execute(
            f"SELECT text, embedding FROM {DENSE_TABLE} WHERE id = %s", (f"{PAGE}#0",)
        ).fetchone()

    asyncio.run(dense.update_metadata(PAGE, {"path": "moved.md"}))

    with psycopg.connect(dense.database_url) as conn:
        after = conn.execute(
            f"SELECT text, embedding FROM {DENSE_TABLE} WHERE id = %s", (f"{PAGE}#0",)
        ).fetchone()
    assert after == before


def test_fts_index_upserts_text_and_makes_it_searchable(fts):
    asyncio.run(
        fts.index(
            [
                Document(
                    id=f"{PAGE}#0",
                    text="notes about kayaking",
                    source=PAGE,
                    metadata={"title": "Kayaks"},
                )
            ]
        )
    )
    [row] = asyncio.run(fts.search("kayaking"))
    assert row["source"] == PAGE
    assert row["metadata"] == {"title": "Kayaks"}

    asyncio.run(
        fts.index(
            [
                Document(
                    id=f"{PAGE}#0",
                    text="notes about canoeing",
                    source=PAGE,
                    metadata={"title": "Canoes"},
                )
            ]
        )
    )

    assert asyncio.run(fts.search("kayaking")) == []
    assert asyncio.run(fts.search("canoeing"))[0]["text"] == "notes about canoeing"


def test_fts_index_of_nothing_is_a_no_op(fts):
    assert asyncio.run(fts.index([])) == []
    assert read_rows(fts.database_url, FTS_TABLE) == []


def test_fts_title_weighting_survives_an_upsert(fts):
    with (
        psycopg.connect(fts.database_url, autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            f"INSERT INTO {FTS_TABLE} (id, text, source, metadata) "
            "VALUES (%s, %s, %s, %s)",
            ("body#0", "a passing mention of kayaking", "b", json.dumps({})),
        )
    asyncio.run(
        fts.index(
            [
                Document(
                    id="title#0",
                    text="unrelated prose entirely",
                    source="t",
                    metadata={"title": "Kayaking"},
                )
            ]
        )
    )

    assert [row["id"] for row in asyncio.run(fts.search("kayaking"))] == [
        "title#0",
        "body#0",
    ]
