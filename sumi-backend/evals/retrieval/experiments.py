"""Registry of every configuration that has been run.

Each entry is reproducible by name, and its notes record why the change was
kept or dropped, so the experiment log lives with the configs it describes.
"""

from dataclasses import replace

from evals.retrieval.runner import ExperimentConfig
from src.retrieval.search_config import BGE_ARM, FTS_ARM, QWEN_ARM, RetrievalConfig

EXPERIMENTS: dict[str, ExperimentConfig] = {
    "baseline-qwen": ExperimentConfig(
        name="baseline-qwen",
        retrieval=RetrievalConfig(arms=(replace(QWEN_ARM, depth=10),)),
        notes="Baseline: dense Qwen3-Embedding-0.6B alone, depth 10.",
    ),
    "baseline-bge-m3": ExperimentConfig(
        name="baseline-bge-m3",
        retrieval=RetrievalConfig(arms=(replace(BGE_ARM, depth=10),)),
        notes="Baseline: dense BGE-M3 alone, depth 10.",
    ),
    "baseline-fts": ExperimentConfig(
        name="baseline-fts",
        retrieval=RetrievalConfig(arms=(replace(FTS_ARM, depth=10),)),
        notes="Baseline: lexical arm alone, to size what it can contribute.",
    ),
    "rrf-qwen-bge": ExperimentConfig(
        name="rrf-qwen-bge",
        retrieval=RetrievalConfig(
            arms=(replace(QWEN_ARM, depth=50), replace(BGE_ARM, depth=50)),
            fusion="rrf",
        ),
        notes=(
            "The two dense arms disagree per query far more than their equal "
            "means suggest (diagnose diff: swings of +-0.8 NDCG), so fusing "
            "them should recover both sides."
        ),
    ),
    "rrf-qwen-bge-fts": ExperimentConfig(
        name="rrf-qwen-bge-fts",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=50),
                replace(BGE_ARM, depth=50),
                replace(FTS_ARM, depth=50),
            ),
            fusion="rrf",
        ),
        notes="Adds the lexical arm to the dense pair.",
    ),
    "rrf-qwen-fts": ExperimentConfig(
        name="rrf-qwen-fts",
        retrieval=RetrievalConfig(
            arms=(replace(QWEN_ARM, depth=50), replace(FTS_ARM, depth=50)),
            fusion="rrf",
        ),
        notes="Is BGE-M3 earning its place in the three-arm fusion?",
    ),
    "rrf-bge-fts": ExperimentConfig(
        name="rrf-bge-fts",
        retrieval=RetrievalConfig(
            arms=(replace(BGE_ARM, depth=50), replace(FTS_ARM, depth=50)),
            fusion="rrf",
        ),
        notes="The same question for Qwen.",
    ),
    "rrf-3arm-d20": ExperimentConfig(
        name="rrf-3arm-d20",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=20),
                replace(BGE_ARM, depth=20),
                replace(FTS_ARM, depth=20),
            ),
            fusion="rrf",
        ),
        notes="Depth lever: a shallower pool per arm concentrates on each arm's best.",
    ),
    "rrf-3arm-d100": ExperimentConfig(
        name="rrf-3arm-d100",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=100),
                replace(BGE_ARM, depth=100),
                replace(FTS_ARM, depth=100),
            ),
            fusion="rrf",
        ),
        notes="Depth lever, the other way: more candidates for agreement to find.",
    ),
    "rrf-3arm-k10": ExperimentConfig(
        name="rrf-3arm-k10",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=50),
                replace(BGE_ARM, depth=50),
                replace(FTS_ARM, depth=50),
            ),
            fusion="rrf",
            rrf_k=10,
        ),
        notes=(
            "Smaller rrf_k sharpens the discount, so a rank-1 hit outweighs "
            "agreement further down."
        ),
    ),
    "rrf-3arm-dense-heavy": ExperimentConfig(
        name="rrf-3arm-dense-heavy",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=50),
                replace(BGE_ARM, depth=50),
                replace(FTS_ARM, depth=50),
            ),
            fusion="rrf",
            weights=(("qwen", 1.0), ("bge-m3", 1.0), ("fts", 0.5)),
        ),
        notes="Halves the lexical arm's vote, keeping it as a tie-breaker.",
    ),
    "rrf-3arm-lexical-heavy": ExperimentConfig(
        name="rrf-3arm-lexical-heavy",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=50),
                replace(BGE_ARM, depth=50),
                replace(FTS_ARM, depth=50),
            ),
            fusion="rrf",
            weights=(("qwen", 1.0), ("bge-m3", 1.0), ("fts", 2.0)),
        ),
        notes="The opposite: the lexical arm leads the bias-free file metrics.",
    ),
}
