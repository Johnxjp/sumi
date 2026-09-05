"""Registry of every configuration that has been run.

Each entry is reproducible by name, and its notes record why the change was
kept or dropped, so the experiment log lives with the configs it describes.
"""

from dataclasses import replace

from evals.retrieval.runner import ExperimentConfig
from src.retrieval.search_config import (
    BGE_ARM,
    FTS_ARM,
    QWEN_ARM,
    QWEN_TITLE_ARM,
    SYNC_CONFIG,
    RetrievalConfig,
)

EXPERIMENTS: dict[str, ExperimentConfig] = {
    "baseline-qwen": ExperimentConfig(
        name="baseline-qwen",
        retrieval=RetrievalConfig(arms=(replace(QWEN_ARM, depth=10),)),
        notes="Baseline: dense Qwen3-Embedding-0.6B alone, depth 10. train ndcg@10 0.567, file-recall@10 0.580.",
    ),
    "baseline-bge-m3": ExperimentConfig(
        name="baseline-bge-m3",
        retrieval=RetrievalConfig(arms=(replace(BGE_ARM, depth=10),)),
        notes="Baseline: dense BGE-M3 alone, depth 10. Ties Qwen on train ndcg@10 (0.567) while disagreeing per query by up to a full point, and is worse on the bias-free file metrics.",
    ),
    "baseline-fts": ExperimentConfig(
        name="baseline-fts",
        retrieval=RetrievalConfig(arms=(replace(FTS_ARM, depth=10),)),
        notes="Baseline: lexical arm alone, to size what it can contribute. Worst judged score of anything (0.236) and the best single-arm file-recall@10 (0.609) at once: 78% of its top-10 has never been labelled, so its NDCG is a floor, not an estimate. Kept as a fusion arm on that evidence.",
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
            "them should recover both sides. DROPPED as a pair: train ndcg@10 0.535, "
            "below either arm alone — at rrf_k=60 fusion dilutes a strong "
            "single-arm rank instead of reinforcing it."
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
        notes=(
            "Adds the lexical arm to the dense pair. KEPT: train ndcg@10 0.579 "
            "beats both baselines and file-recall@10 0.647 beats all of them."
        ),
    ),
    "rrf-qwen-fts": ExperimentConfig(
        name="rrf-qwen-fts",
        retrieval=RetrievalConfig(
            arms=(replace(QWEN_ARM, depth=50), replace(FTS_ARM, depth=50)),
            fusion="rrf",
        ),
        notes=(
            "Is BGE-M3 earning its place? Yes — dropping it costs 0.117 train "
            "ndcg@10 (0.462), though it buys the best two-arm file-recall."
        ),
    ),
    "rrf-bge-fts": ExperimentConfig(
        name="rrf-bge-fts",
        retrieval=RetrievalConfig(
            arms=(replace(BGE_ARM, depth=50), replace(FTS_ARM, depth=50)),
            fusion="rrf",
        ),
        notes=(
            "The same question for Qwen: also yes, 0.462. Neither dense arm is "
            "redundant."
        ),
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
        notes=(
            "Depth lever: a shallower pool concentrates on each arm's best. "
            "KEPT on its own (0.650), but superseded by rrf_k, which fixes "
            "the same dilution without discarding candidates."
        ),
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
        notes=(
            "Depth lever the other way. DROPPED: 0.603, worse than depth 50 — "
            "deeper candidates add agreement noise, not signal."
        ),
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
            "agreement further down. KEPT: 0.656, and the first hint that rrf_k "
            "was the dominant lever."
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
        notes=(
            "Halves the lexical arm's vote. DROPPED: 0.527. The lexical arm "
            "earns a full vote."
        ),
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
        notes=(
            "The opposite weighting. DROPPED: 0.431 — best-in-class file-recall "
            "(0.691) cannot rescue the judged metric. Equal weights win."
        ),
    ),
    "rrf-3arm-k10-d20": ExperimentConfig(
        name="rrf-3arm-k10-d20",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=20),
                replace(BGE_ARM, depth=20),
                replace(FTS_ARM, depth=20),
            ),
            fusion="rrf",
            rrf_k=10,
        ),
        notes=(
            "Both sharpening levers at once, each having won on its own. "
            "They fix the same failure — at depth 50 with k=60, two mediocre "
            "ranks (1/80 + 1/80) outvote one strong one (1/63), so positives "
            "an arm ranked 3rd fell out of the top 10. 0.664 — better than either "
            "alone, but below rrf_k=5 at full depth, so depth 50 stays."
        ),
    ),
    "rrf-3arm-k5": ExperimentConfig(
        name="rrf-3arm-k5",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=50),
                replace(BGE_ARM, depth=50),
                replace(FTS_ARM, depth=50),
            ),
            fusion="rrf",
            rrf_k=5,
        ),
        notes=(
            "Is the rrf_k optimum below 10? Yes, and this is it: train ndcg@10 "
            "0.712, precision@10 0.233 above every baseline, file-recall@10 "
            "0.710, val 0.825. WINNER — shipped as ACTIVE_CONFIG."
        ),
    ),
    "rrf-3arm-k5-notion": ExperimentConfig(
        name="rrf-3arm-k5-notion",
        retrieval=SYNC_CONFIG,
        notes=(
            "The shipped configuration, arm for arm, over the tables the Notion "
            "sync fills instead of the ones built from the hand-made export. Same "
            "queries, same labels, two corpora: the difference from rrf-3arm-k5 "
            "measures how much the notes themselves moved on (pages added and "
            "edited since 2026-08-09) plus judgments whose text no longer exists, "
            "not a change in how retrieval works. Not run yet - it needs a full "
            "sync first."
        ),
    ),
    "rrf-3arm-k30": ExperimentConfig(
        name="rrf-3arm-k30",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=50),
                replace(BGE_ARM, depth=50),
                replace(FTS_ARM, depth=50),
            ),
            fusion="rrf",
            rrf_k=30,
        ),
        notes=(
            "Brackets rrf_k between the 10 that won and the 60 that lost: "
            "0.600, on the monotone stretch."
        ),
    ),
    "rrf-3arm-k2": ExperimentConfig(
        name="rrf-3arm-k2",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=50),
                replace(BGE_ARM, depth=50),
                replace(FTS_ARM, depth=50),
            ),
            fusion="rrf",
            rrf_k=2,
        ),
        notes=(
            "NDCG rises monotonically as rrf_k falls (60 -> 30 -> 10 -> 5); "
            "this is where it turns back down: 0.690."
        ),
    ),
    "rrf-3arm-k1": ExperimentConfig(
        name="rrf-3arm-k1",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_ARM, depth=50),
                replace(BGE_ARM, depth=50),
                replace(FTS_ARM, depth=50),
            ),
            fusion="rrf",
            rrf_k=1,
        ),
        notes=(
            "The far end of the lever: at k=1 a rank-1 hit (0.50) outweighs "
            "any pair of agreeing ranks below 3rd, so fusion nearly degenerates "
            "to best-rank-wins. 0.678, confirming k=5 as the optimum rather than "
            "the edge of the range tested."
        ),
    ),
    "baseline-qwen-title": ExperimentConfig(
        name="baseline-qwen-title",
        retrieval=RetrievalConfig(arms=(replace(QWEN_TITLE_ARM, depth=10),)),
        notes=(
            "Metadata lever in isolation: the same Qwen model over chunks "
            "embedded with their note title prepended. DROPPED: +0.007 ndcg@10 but "
            "-0.005 file-recall and -0.017 file-mrr against baseline-qwen — a "
            "wash, for a full re-ingest. The table and --title-prefix remain."
        ),
    ),
    "rrf-3arm-k10-title": ExperimentConfig(
        name="rrf-3arm-k10-title",
        retrieval=RetrievalConfig(
            arms=(
                replace(QWEN_TITLE_ARM, depth=50),
                replace(BGE_ARM, depth=50),
                replace(FTS_ARM, depth=50),
            ),
            fusion="rrf",
            rrf_k=10,
        ),
        notes=(
            "The title-prefixed table swapped into the leading configuration. "
            "DROPPED: 0.646 against 0.656 for plain qwen at the same rrf_k."
        ),
    ),
}
