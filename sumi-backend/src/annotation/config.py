"""Retriever declarations for the annotation tool. Plain Python, no env vars."""

from src.annotation.retrievers import RetrieverConfig

RETRIEVER_CONFIGS = [
    RetrieverConfig(name="qwen", type="pgvector", embedder="qwen", table="chunks_qwen"),
    RetrieverConfig(
        name="bge-m3", type="pgvector", embedder="bge-m3", table="chunks_bge_m3"
    ),
    # Pools the lexical arm too, so chunks only it surfaces can be labeled.
    RetrieverConfig(name="fts", type="fts", table="chunks_fts"),
]
