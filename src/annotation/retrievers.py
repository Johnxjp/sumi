import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.config import app_config
from src.retrieval.embedder import GeminiEmbedder, QwenEmbedder
from src.retrieval.indexer import BreadBowlIndexer, Indexer, PgVectorIndexer


class RetrieverConfig(BaseModel):
    name: str
    type: str = "breadbowl"
    index_id: str | None = None
    chunks_file: str | None = None
    table: str | None = None
    embedder: str | None = None


class StaticRetriever(Indexer):
    """Serves canned results from a JSON file. Reference for the search() contract."""

    def __init__(self, chunks_file: Path) -> None:
        self.chunks_file = chunks_file

    def index(self, documents: list[str]):
        raise NotImplementedError("Static retriever cannot index.")

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        with open(self.chunks_file, encoding="utf-8") as f:
            results = json.load(f)
        return results[:top_k] if top_k is not None else results


def build_retriever(config: RetrieverConfig, base_dir: Path) -> Indexer:
    if config.type == "breadbowl":
        if not config.index_id:
            raise ValueError(f"Retriever '{config.name}' requires an index_id.")
        api_base_url = os.getenv("BREADBOWL_API_URL")
        api_key = os.getenv("BREADBOWL_API_KEY")
        if not api_base_url or not api_key:
            raise ValueError(
                "BREADBOWL_API_URL and BREADBOWL_API_KEY must be set for "
                f"retriever '{config.name}'."
            )
        return BreadBowlIndexer(
            api_base_url=api_base_url, api_key=api_key, index_id=config.index_id
        )
    if config.type == "static":
        if not config.chunks_file:
            raise ValueError(f"Retriever '{config.name}' requires a chunks_file.")
        return StaticRetriever(base_dir / config.chunks_file)
    if config.type == "pgvector":
        if not config.table:
            raise ValueError(f"Retriever '{config.name}' requires a table.")
        if config.embedder == "qwen":
            embedder = QwenEmbedder()
            dimensions = embedder.output_dimensionality
        elif config.embedder == "gemini":
            dimensions = app_config.embedding_dimensions
            embedder = GeminiEmbedder(
                api_key=app_config.gemini_api_key,
                output_dimensionality=dimensions,
            )
        else:
            raise ValueError(
                f"Retriever '{config.name}' requires embedder 'qwen' or 'gemini', "
                f"got {config.embedder!r}."
            )
        return PgVectorIndexer(
            app_config.database_url,
            embedder=embedder,
            dimensions=dimensions,
            table=config.table,
        )
    raise ValueError(f"Unknown retriever type '{config.type}' for '{config.name}'.")


def load_retrievers(path: Path) -> dict[str, Indexer]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    retrievers: dict[str, Indexer] = {}
    for entry in raw["retrievers"]:
        config = RetrieverConfig(**entry)
        if config.name in retrievers:
            raise ValueError(f"Duplicate retriever name '{config.name}'.")
        retrievers[config.name] = build_retriever(config, path.parent)
    return retrievers
