import asyncio

import psycopg
import pytest

from src.retrieval.indexer import Document, PgVectorIndexer


def _postgres_available() -> bool:
    try:
        with psycopg.connect("postgresql://localhost:5432/postgres", connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(), reason="local Postgres is not running"
)


class FakeEmbedder:
    """Returns fixed vectors per text so similarity ordering is controlled."""

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    async def embed_documents(self, texts, titles=None):
        return [self.vectors[text] for text in texts]

    async def embed_query(self, text):
        return self.vectors[text]


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


def make_indexer(test_db_url: str, vectors: dict[str, list[float]]) -> PgVectorIndexer:
    indexer = PgVectorIndexer(
        test_db_url,
        embedder=FakeEmbedder(vectors),
        dimensions=3,
        table="chunks_test",
    )
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS chunks_test")
    asyncio.run(indexer.ensure_schema())
    return indexer


def test_ensure_schema_is_idempotent(test_db_url):
    indexer = make_indexer(test_db_url, {})
    asyncio.run(indexer.ensure_schema())


def test_index_and_search_orders_by_similarity(test_db_url):
    indexer = make_indexer(
        test_db_url,
        {
            "all about apples": [1.0, 0.0, 0.0],
            "all about bananas": [0.0, 1.0, 0.0],
            "apples?": [0.9, 0.1, 0.0],
        },
    )
    failed = asyncio.run(
        indexer.index(
            [
                Document(
                    id="a",
                    text="all about apples",
                    source="notes/apples.md",
                    metadata={},
                ),
                Document(
                    id="b",
                    text="all about bananas",
                    source="notes/bananas.md",
                    metadata={},
                ),
            ]
        )
    )
    assert failed == []
    results = asyncio.run(indexer.search("apples?"))
    assert [r["id"] for r in results] == ["a", "b"]
    assert results[0]["score"] > results[1]["score"]
    assert results[0]["text"] == "all about apples"
    assert results[0]["source"] == "notes/apples.md"


def test_top_k_limits_results(test_db_url):
    indexer = make_indexer(
        test_db_url,
        {
            "all about apples": [1.0, 0.0, 0.0],
            "all about bananas": [0.0, 1.0, 0.0],
            "apples?": [0.9, 0.1, 0.0],
        },
    )
    asyncio.run(
        indexer.index(
            [
                Document(
                    id="a",
                    text="all about apples",
                    source="notes/apples.md",
                    metadata={},
                ),
                Document(
                    id="b",
                    text="all about bananas",
                    source="notes/bananas.md",
                    metadata={},
                ),
            ]
        )
    )
    assert len(asyncio.run(indexer.search("apples?", top_k=1))) == 1


def test_reindexing_same_id_upserts(test_db_url):
    indexer = make_indexer(
        test_db_url,
        {
            "all about apples": [1.0, 0.0, 0.0],
            "all about bananas": [0.0, 1.0, 0.0],
            "apples?": [0.9, 0.1, 0.0],
        },
    )
    asyncio.run(
        indexer.index(
            [
                Document(
                    id="a",
                    text="all about apples",
                    source="notes/apples.md",
                    metadata={},
                )
            ]
        )
    )
    asyncio.run(
        indexer.index(
            [
                Document(
                    id="a",
                    text="all about bananas",
                    source="notes/bananas.md",
                    metadata={},
                )
            ]
        )
    )
    results = asyncio.run(indexer.search("apples?"))
    assert len(results) == 1
    assert results[0]["text"] == "all about bananas"


def test_search_deeper_than_the_hnsw_default_returns_every_row(test_db_url):
    # Enough rows that the planner prefers the HNSW index, whose scan visits
    # hnsw.ef_search (default 40) candidates and would otherwise truncate.
    texts = [f"doc {i}" for i in range(600)]
    vectors = {text: [1.0, i / 600, (i % 7) / 7] for i, text in enumerate(texts)}
    vectors["query"] = [1.0, 0.0, 0.0]
    indexer = make_indexer(test_db_url, vectors)
    asyncio.run(
        indexer.index(
            [
                Document(id=f"d{i}", text=text, source="notes/s.md", metadata={})
                for i, text in enumerate(texts)
            ]
        )
    )

    assert len(asyncio.run(indexer.search("query", top_k=60))) == 60


def test_metadata_round_trip(test_db_url):
    indexer = make_indexer(test_db_url, {"all about apples": [1.0, 0.0, 0.0]})
    metadata = {"title": "Apples", "tags": ["fruit", "notes"]}
    asyncio.run(
        indexer.index(
            [
                Document(
                    id="a",
                    text="all about apples",
                    source="notes/apples.md",
                    metadata=metadata,
                )
            ]
        )
    )
    results = asyncio.run(indexer.search("all about apples"))
    assert results[0]["metadata"] == metadata
