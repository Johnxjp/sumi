import asyncio
from unittest import mock

import pytest

from src.retrieval.embedder import BgeM3Embedder, QwenEmbedder
from src.retrieval.indexer import PgVectorIndexer
from src.retrieval.lexical import PgFtsIndexer
from src.retrieval.retrieve import HybridRetriever, build_arm_indexer
from src.retrieval.search_config import ArmConfig, RetrievalConfig

DB_URL = "postgresql://localhost:5432/nowhere"


class FakeArm:
    """Records the depth it was asked for and serves canned rows."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.requested_top_k = None

    async def search(self, query: str, top_k: int | None = None) -> list[dict]:
        self.requested_top_k = top_k
        return self.rows[:top_k]


def make_row(row_id: str, score: float = 0.5) -> dict:
    return {
        "id": row_id,
        "text": f"text {row_id}",
        "source": f"{row_id}.md",
        "metadata": {},
        "score": score,
    }


def make_retriever(
    config: RetrievalConfig, arms: dict[str, FakeArm]
) -> HybridRetriever:
    with mock.patch(
        "src.retrieval.retrieve.build_arm_indexer",
        side_effect=lambda arm, _: arms[arm.name],
    ):
        return HybridRetriever(config, database_url=DB_URL)


def test_single_arm_passes_through_with_its_own_scores():
    arm = ArmConfig(name="qwen", kind="dense", table="chunks_qwen", embedder="qwen")
    fake = FakeArm([make_row("a", 0.9), make_row("b", 0.8), make_row("c", 0.7)])
    retriever = make_retriever(RetrievalConfig(arms=(arm,)), {"qwen": fake})

    results = asyncio.run(retriever.retrieve("q", top_k=2))

    assert [row["id"] for row in results] == ["a", "b"]
    assert [row["score"] for row in results] == [0.9, 0.8]
    assert [row["arms"] for row in results] == [{"qwen": 1}, {"qwen": 2}]


def test_arms_are_searched_at_their_configured_depth():
    arm = ArmConfig(
        name="qwen", kind="dense", table="chunks_qwen", embedder="qwen", depth=25
    )
    fake = FakeArm([make_row("a")])
    retriever = make_retriever(RetrievalConfig(arms=(arm,)), {"qwen": fake})

    asyncio.run(retriever.retrieve("q"))

    assert fake.requested_top_k == 25


def test_multiple_arms_are_fused_and_truncated():
    arms = (
        ArmConfig(name="qwen", kind="dense", table="chunks_qwen", embedder="qwen"),
        ArmConfig(name="fts", kind="lexical", table="chunks_fts"),
    )
    fakes = {
        "qwen": FakeArm([make_row("a"), make_row("b")]),
        "fts": FakeArm([make_row("c"), make_row("a")]),
    }
    retriever = make_retriever(RetrievalConfig(arms=arms, fusion="rrf", top_k=2), fakes)

    results = asyncio.run(retriever.retrieve("q"))

    # "a" is found by both arms, then "c" at rank 1 beats "b" at rank 2.
    assert [row["id"] for row in results] == ["a", "c"]
    assert results[0]["arms"] == {"qwen": 1, "fts": 2}


def test_weights_are_applied_when_fusing():
    arms = (
        ArmConfig(name="qwen", kind="dense", table="chunks_qwen", embedder="qwen"),
        ArmConfig(name="fts", kind="lexical", table="chunks_fts"),
    )
    fakes = {"qwen": FakeArm([make_row("a")]), "fts": FakeArm([make_row("b")])}
    retriever = make_retriever(
        RetrievalConfig(arms=arms, fusion="rrf", weights=(("qwen", 0.1), ("fts", 5.0))),
        fakes,
    )

    results = asyncio.run(retriever.retrieve("q"))

    assert [row["id"] for row in results] == ["b", "a"]


def test_single_fusion_with_several_arms_is_rejected():
    arms = (
        ArmConfig(name="qwen", kind="dense", table="chunks_qwen", embedder="qwen"),
        ArmConfig(name="fts", kind="lexical", table="chunks_fts"),
    )
    fakes = {"qwen": FakeArm([]), "fts": FakeArm([])}
    retriever = make_retriever(RetrievalConfig(arms=arms), fakes)

    with pytest.raises(ValueError, match="exactly one arm"):
        asyncio.run(retriever.retrieve("q"))


@pytest.mark.parametrize(
    ("embedder", "table", "expected"),
    [
        ("qwen", "chunks_qwen", QwenEmbedder),
        ("qwen", "chunks_qwen_title", QwenEmbedder),
        ("bge-m3", "chunks_bge_m3", BgeM3Embedder),
    ],
)
def test_build_arm_indexer_pairs_embedder_with_its_table(embedder, table, expected):
    indexer = build_arm_indexer(
        ArmConfig(name="arm", kind="dense", table=table, embedder=embedder), DB_URL
    )
    assert isinstance(indexer, PgVectorIndexer)
    assert isinstance(indexer.embedder, expected)
    assert indexer.dimensions == indexer.embedder.output_dimensionality


def test_build_arm_indexer_builds_the_lexical_arm():
    indexer = build_arm_indexer(
        ArmConfig(name="fts", kind="lexical", table="chunks_fts"), DB_URL
    )
    assert isinstance(indexer, PgFtsIndexer)
    assert indexer.table == "chunks_fts"


@pytest.mark.parametrize(
    ("arm", "message"),
    [
        (
            ArmConfig(name="a", kind="dense", table="chunks_qwen", embedder=None),
            "requires an embedder",
        ),
        (
            ArmConfig(name="a", kind="dense", table="chunks_qwen", embedder="gemini"),
            "Unknown embedder",
        ),
        (
            ArmConfig(name="a", kind="dense", table="chunks_bge_m3", embedder="qwen"),
            "expected a chunks_qwen",
        ),
    ],
)
def test_build_arm_indexer_rejects_invalid_arms(arm, message):
    with pytest.raises(ValueError, match=message):
        build_arm_indexer(arm, DB_URL)
