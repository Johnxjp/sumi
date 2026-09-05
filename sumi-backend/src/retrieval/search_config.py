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

# The same three arms over the tables the Notion sync fills. Their names keep
# the prefixes build_arm_indexer checks, so an arm still cannot be paired with
# a table another embedder built.
QWEN_NOTION_ARM = replace(QWEN_ARM, table="chunks_qwen_notion")
BGE_NOTION_ARM = replace(BGE_ARM, table="chunks_bge_m3_notion")
FTS_NOTION_ARM = replace(FTS_ARM, table="chunks_fts_notion")

# The settings that ship, and the ones the sync writes for. Winner of the
# experiment sweep in evals/retrieval/experiments.py ("rrf-3arm-k5"): train
# NDCG@10 0.712 against 0.567 for the best single arm. rrf_k is the lever that
# mattered — at the usual 60, two arms agreeing at rank 40 outvote one arm's
# rank-3 hit, and judged positives fell out of the top 10.
SYNC_CONFIG = RetrievalConfig(
    arms=(
        replace(QWEN_NOTION_ARM, depth=50),
        replace(BGE_NOTION_ARM, depth=50),
        replace(FTS_NOTION_ARM, depth=50),
    ),
    fusion="rrf",
    rrf_k=5,
    top_k=10,
)

# The same settings over the export-built tables. That corpus is frozen: it is
# what the human relevance judgments were made on, so eval experiments name it
# and nothing writes to it. Searches no longer read it.
FROZEN_EVAL_CONFIG = RetrievalConfig(
    arms=(
        replace(QWEN_ARM, depth=50),
        replace(BGE_ARM, depth=50),
        replace(FTS_ARM, depth=50),
    ),
    fusion="rrf",
    rrf_k=5,
    top_k=10,
)

# What every search runs: the corpus Notion syncs into, kept current by
# scripts/sync.py. ACTIVE_CONFIG_NAME labels each line of the usage log, so a
# logged search can be read against the settings that answered it.
ACTIVE_CONFIG_NAME = "rrf-3arm-k5-notion"
ACTIVE_CONFIG = SYNC_CONFIG
