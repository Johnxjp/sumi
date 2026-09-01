"""Declarative retrieval configuration. Plain Python, no env vars."""

from dataclasses import dataclass, replace
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
QWEN_TITLE_ARM = ArmConfig(
    name="qwen-title", kind="dense", table="chunks_qwen_title", embedder="qwen"
)
FTS_ARM = ArmConfig(name="fts", kind="lexical", table="chunks_fts")

# Winner of the experiment sweep in evals/retrieval/experiments.py ("rrf-3arm-k5"):
# train NDCG@10 0.712 against 0.567 for the best single arm. rrf_k is the lever
# that mattered — at the usual 60, two arms agreeing at rank 40 outvote one arm's
# rank-3 hit, and judged positives fell out of the top 10.
ACTIVE_CONFIG = RetrievalConfig(
    arms=(
        replace(QWEN_ARM, depth=50),
        replace(BGE_ARM, depth=50),
        replace(FTS_ARM, depth=50),
    ),
    fusion="rrf",
    rrf_k=5,
    top_k=10,
)
