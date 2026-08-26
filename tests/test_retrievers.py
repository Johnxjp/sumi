import json

import pytest

from src.annotation.retrievers import RetrieverConfig, build_retriever, load_retrievers
from src.retrieval.embedder import BgeM3Embedder, QwenEmbedder
from src.retrieval.indexer import PgVectorIndexer


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


def test_build_pgvector_requires_table(tmp_path):
    config = RetrieverConfig(name="qwen", type="pgvector", embedder="qwen")
    with pytest.raises(ValueError, match="table"):
        build_retriever(config, tmp_path)


def test_build_pgvector_rejects_unknown_embedder(tmp_path):
    config = RetrieverConfig(name="x", type="pgvector", embedder="bert", table="t")
    with pytest.raises(ValueError, match="embedder"):
        build_retriever(config, tmp_path)


def test_load_retrievers_rejects_duplicate_names(tmp_path):
    path = tmp_path / "retrievers.json"
    entry = {"name": "a", "type": "static", "chunks_file": "chunks.json"}
    path.write_text(json.dumps({"retrievers": [entry, entry]}))
    with pytest.raises(ValueError, match="Duplicate"):
        load_retrievers(path)
