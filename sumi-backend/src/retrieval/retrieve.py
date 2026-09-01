"""Candidate retrieval: the query-time entry point into the index."""

import asyncio
from functools import lru_cache
from typing import Any

from src.config import app_config
from src.retrieval.embedder import BgeM3Embedder, Embedder, QwenEmbedder
from src.retrieval.fusion import fuse_rrf
from src.retrieval.indexer import Indexer, PgVectorIndexer
from src.retrieval.lexical import PgFtsIndexer
from src.retrieval.search_config import ACTIVE_CONFIG, ArmConfig, RetrievalConfig

# A dense arm is only valid on the table built with its own embedder: the
# vectors of two models are not comparable, and Qwen additionally encodes
# queries with a prompt its table's documents were embedded without.
EMBEDDER_TABLE_PREFIX = {"qwen": "chunks_qwen", "bge-m3": "chunks_bge_m3"}


def build_embedder(name: str) -> Embedder:
    if name == "qwen":
        return QwenEmbedder()
    if name == "bge-m3":
        return BgeM3Embedder()
    raise ValueError(f"Unknown embedder {name!r}; expected 'qwen' or 'bge-m3'.")


def build_arm_indexer(arm: ArmConfig, database_url: str) -> Indexer:
    if arm.kind == "lexical":
        return PgFtsIndexer(database_url, table=arm.table)
    if arm.embedder is None:
        raise ValueError(f"Dense arm {arm.name!r} requires an embedder.")
    prefix = EMBEDDER_TABLE_PREFIX.get(arm.embedder)
    if prefix is None:
        raise ValueError(
            f"Unknown embedder {arm.embedder!r} for arm {arm.name!r}; "
            "expected 'qwen' or 'bge-m3'."
        )
    if not arm.table.startswith(prefix):
        raise ValueError(
            f"Arm {arm.name!r} pairs embedder {arm.embedder!r} with table "
            f"{arm.table!r}; expected a {prefix}* table."
        )
    embedder = build_embedder(arm.embedder)
    return PgVectorIndexer(
        database_url,
        embedder=embedder,
        dimensions=embedder.output_dimensionality,
        table=arm.table,
    )


class HybridRetriever:
    """Runs the configured arms and fuses their candidates into one ranking."""

    def __init__(self, config: RetrievalConfig, database_url: str | None = None):
        self.config = config
        url = database_url or app_config.database_url
        # Arms are built once: a dense arm loads a sentence-transformers model.
        self.arms = {arm.name: build_arm_indexer(arm, url) for arm in config.arms}

    async def retrieve_arms(self, query: str) -> dict[str, list[dict[str, Any]]]:
        """Candidates per arm at that arm's depth, best first."""
        results = await asyncio.gather(
            *(
                self.arms[arm.name].search(query, top_k=arm.depth)
                for arm in self.config.arms
            )
        )
        return {
            arm.name: rows for arm, rows in zip(self.config.arms, results, strict=True)
        }

    async def retrieve(
        self, query: str, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        per_arm = await self.retrieve_arms(query)
        return self.merge(per_arm)[: top_k if top_k is not None else self.config.top_k]

    def merge(self, per_arm: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        """Fuse arm results, or pass a single arm through with its own scores."""
        if self.config.fusion == "single":
            if len(per_arm) != 1:
                raise ValueError(
                    f"fusion='single' needs exactly one arm, got {len(per_arm)}."
                )
            [(name, rows)] = per_arm.items()
            return [{**row, "arms": {name: rank}} for rank, row in enumerate(rows, 1)]
        weights = dict(self.config.weights) if self.config.weights else None
        return fuse_rrf(per_arm, k=self.config.rrf_k, weights=weights)


@lru_cache(maxsize=1)
def get_default_retriever() -> HybridRetriever:
    """Cached so repeated calls reuse the loaded embedding models."""
    return HybridRetriever(ACTIVE_CONFIG)


async def retrieve(query: str, top_k: int = 10) -> list[dict[str, Any]]:
    """Return the top_k most relevant note chunks for a query."""
    return await get_default_retriever().retrieve(query, top_k=top_k)
