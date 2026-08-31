"""Declarative retrieval configuration. Plain Python, no env vars."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ArmConfig:
    """One candidate generator: a dense table + its embedder, or the FTS table."""

    name: str
    kind: Literal["dense", "lexical"]
    table: str
    embedder: str | None = None
    depth: int = 50


@dataclass(frozen=True)
class RetrievalConfig:
    arms: tuple[ArmConfig, ...]
    fusion: Literal["single", "rrf"] = "single"
    rrf_k: int = 60
    weights: tuple[tuple[str, float], ...] | None = None
    top_k: int = 10


QWEN_ARM = ArmConfig(name="qwen", kind="dense", table="chunks_qwen", embedder="qwen")
BGE_ARM = ArmConfig(
    name="bge-m3", kind="dense", table="chunks_bge_m3", embedder="bge-m3"
)
FTS_ARM = ArmConfig(name="fts", kind="lexical", table="chunks_fts")

ACTIVE_CONFIG = RetrievalConfig(arms=(QWEN_ARM,), top_k=10)
