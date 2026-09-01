import pytest

from src.annotation.retrievers import RetrieverConfig, build_retriever, build_retrievers
from src.retrieval.embedder import BgeM3Embedder, QwenEmbedder
from src.retrieval.indexer import PgVectorIndexer
from src.retrieval.lexical import PgFtsIndexer


@pytest.mark.parametrize(
    ("embedder_name", "embedder_cls", "table"),
    [
        ("qwen", QwenEmbedder, "chunks_qwen"),
        ("bge-m3", BgeM3Embedder, "chunks_bge_m3"),
    ],
)
def test_build_pgvector_local_embedder(tmp_path, embedder_name, embedder_cls, table):
    config = RetrieverConfig(
        name=embedder_name, type="pgvector", embedder=embedder_name, table=table
    )
    retriever = build_retriever(config, tmp_path)
    assert isinstance(retriever, PgVectorIndexer)
    assert retriever.table == table
    assert isinstance(retriever.embedder, embedder_cls)
    assert retriever.dimensions == retriever.embedder.output_dimensionality


@pytest.mark.parametrize(
    "config",
    [
        RetrieverConfig(name="qwen", type="pgvector", embedder="qwen"),
        RetrieverConfig(name="fts", type="fts"),
    ],
    ids=["pgvector", "fts"],
)
def test_build_retriever_requires_table(tmp_path, config):
    with pytest.raises(ValueError, match="table"):
        build_retriever(config, tmp_path)


def test_build_pgvector_rejects_unknown_embedder(tmp_path):
    config = RetrieverConfig(name="x", type="pgvector", embedder="bert", table="t")
    with pytest.raises(ValueError, match="embedder"):
        build_retriever(config, tmp_path)


def test_build_retrievers_rejects_duplicate_names(tmp_path):
    config = RetrieverConfig(name="a", type="static", chunks_file="chunks.json")
    with pytest.raises(ValueError, match="Duplicate"):
        build_retrievers([config, config], tmp_path)


def test_build_fts_retriever(tmp_path):
    config = RetrieverConfig(name="fts", type="fts", table="chunks_fts")
    retriever = build_retriever(config, tmp_path)
    assert isinstance(retriever, PgFtsIndexer)
    assert retriever.table == "chunks_fts"
