import asyncio
from dataclasses import replace
from unittest import mock

import pytest

from src.retrieval.embedder import (
    BgeM3Embedder,
    QwenEmbedder,
    SentenceTransformerEmbedder,
)
from src.retrieval.indexer import PgVectorIndexer
from src.retrieval.lexical import PgFtsIndexer
from src.retrieval.retrieve import HybridRetriever, build_arm_indexer
from src.retrieval.search_config import ArmConfig, RetrievalConfig

DB_URL = "postgresql://localhost:5432/nowhere"
QWEN = ArmConfig(name="qwen", kind="dense", table="chunks_qwen", embedder="qwen")
BGE = ArmConfig(name="bge-m3", kind="dense", table="chunks_bge_m3", embedder="bge-m3")
FTS = ArmConfig(name="fts", kind="lexical", table="chunks_fts")


def make_row(row_id: str, score: float = 0.5) -> dict:
    return {
        "id": row_id,
        "text": f"text {row_id}",
        "source": f"{row_id}.md",
        "metadata": {},
        "score": score,
    }


def make_arm(rows: list[dict]) -> mock.NonCallableMagicMock:
    arm = mock.create_autospec(PgVectorIndexer, instance=True)
    arm.search.side_effect = lambda query, top_k=None: rows[:top_k]
    return arm


def make_retriever(
    build_arm_indexer: mock.MagicMock, config: RetrievalConfig, *arms
) -> HybridRetriever:
    build_arm_indexer.side_effect = list(arms)
    return HybridRetriever(config, database_url=DB_URL)


@mock.patch("src.retrieval.retrieve.build_arm_indexer", autospec=True)
def test_single_arm_passes_through_with_its_own_scores(build_arm_indexer):
    arm = make_arm([make_row("a", 0.9), make_row("b", 0.8), make_row("c", 0.7)])
    retriever = make_retriever(build_arm_indexer, RetrievalConfig(arms=(QWEN,)), arm)

    results = asyncio.run(retriever.retrieve("q", top_k=2))

    assert [row["id"] for row in results] == ["a", "b"]
    assert [row["score"] for row in results] == [0.9, 0.8]
    assert [row["arms"] for row in results] == [{"qwen": 1}, {"qwen": 2}]


@mock.patch("src.retrieval.retrieve.build_arm_indexer", autospec=True)
def test_arms_are_searched_at_their_configured_depth(build_arm_indexer):
    arm = make_arm([make_row("a")])
    config = RetrievalConfig(arms=(replace(QWEN, depth=25),))
    retriever = make_retriever(build_arm_indexer, config, arm)

    asyncio.run(retriever.retrieve("q"))

    arm.search.assert_awaited_once_with("q", top_k=25)


@mock.patch("src.retrieval.retrieve.build_arm_indexer", autospec=True)
def test_multiple_arms_are_fused_and_truncated(build_arm_indexer):
    qwen = make_arm([make_row("a"), make_row("b")])
    fts = make_arm([make_row("c"), make_row("a")])
    config = RetrievalConfig(arms=(QWEN, FTS), fusion="rrf", top_k=2)
    retriever = make_retriever(build_arm_indexer, config, qwen, fts)

    results = asyncio.run(retriever.retrieve("q"))

    # "a" is found by both arms, then "c" at rank 1 beats "b" at rank 2.
    assert [row["id"] for row in results] == ["a", "c"]
    assert results[0]["arms"] == {"qwen": 1, "fts": 2}


@mock.patch("src.retrieval.retrieve.build_arm_indexer", autospec=True)
def test_weights_are_applied_when_fusing(build_arm_indexer):
    config = RetrievalConfig(
        arms=(QWEN, FTS), fusion="rrf", weights=(("qwen", 0.1), ("fts", 5.0))
    )
    retriever = make_retriever(
        build_arm_indexer, config, make_arm([make_row("a")]), make_arm([make_row("b")])
    )

    results = asyncio.run(retriever.retrieve("q"))

    assert [row["id"] for row in results] == ["b", "a"]


@mock.patch("src.retrieval.retrieve.build_arm_indexer", autospec=True)
def test_single_fusion_with_several_arms_is_rejected(build_arm_indexer):
    retriever = make_retriever(
        build_arm_indexer, RetrievalConfig(arms=(QWEN, FTS)), make_arm([]), make_arm([])
    )

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
    indexer = build_arm_indexer(FTS, DB_URL)
    assert isinstance(indexer, PgFtsIndexer)
    assert indexer.table == "chunks_fts"


@pytest.mark.parametrize(
    ("arm", "message"),
    [
        (replace(QWEN, embedder=None), "requires an embedder"),
        (replace(QWEN, embedder="gemini"), "Unknown embedder"),
        (replace(QWEN, table="chunks_bge_m3"), "expected a chunks_qwen"),
    ],
)
def test_build_arm_indexer_rejects_invalid_arms(arm, message):
    with pytest.raises(ValueError, match=message):
        build_arm_indexer(arm, DB_URL)


@mock.patch.object(SentenceTransformerEmbedder, "load_model", autospec=True)
def test_load_models_loads_each_dense_arm_and_skips_the_lexical_one(load_model):
    config = RetrievalConfig(arms=(QWEN, BGE, FTS), fusion="rrf")
    retriever = HybridRetriever(config, database_url=DB_URL)

    retriever.load_models()

    assert load_model.call_args_list == [
        mock.call(retriever.arms["qwen"].embedder),
        mock.call(retriever.arms["bge-m3"].embedder),
    ]
