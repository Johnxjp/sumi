import json

import pytest

from src.annotation.retrievers import RetrieverConfig, build_retriever, load_retrievers
from src.retrieval.embedder import QwenEmbedder
from src.retrieval.indexer import PgVectorIndexer


def test_build_pgvector_qwen(tmp_path):
    config = RetrieverConfig(
        name="qwen", type="pgvector", embedder="qwen", table="chunks_qwen"
    )
    retriever = build_retriever(config, tmp_path)
    assert isinstance(retriever, PgVectorIndexer)
    assert retriever.table == "chunks_qwen"
    assert isinstance(retriever.embedder, QwenEmbedder)
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
