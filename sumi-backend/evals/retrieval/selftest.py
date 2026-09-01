"""Check that judgments join back onto fresh retrieval results.

`uv run python -m evals.retrieval.selftest` — re-runs the arm the annotation
pool was built from and asserts every judgment it contributed is matched
again by the qrels join. If this fails, every NDCG in every run is wrong, so
run it before trusting a new number.

It also reports judged coverage, which is a property of how much labeling has
been done, not of the join: the pool was labeled from the top down and left a
tail unlabeled, so coverage below 1.0 is expected and only means the reported
NDCG is a lower bound.
"""

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path

from evals.retrieval import paths
from evals.retrieval.qrels import load_graded_qrels, lookup_gain
from src.annotation.store import normalize_query
from src.retrieval.retrieve import HybridRetriever
from src.retrieval.search_config import BGE_ARM, QWEN_ARM, RetrievalConfig

POOL_DEPTH = 10
POOL_ARMS = {"qwen": QWEN_ARM, "bge-m3": BGE_ARM}


def find_pooled_chunk_ids(
    path: Path, retriever: str, max_rank: int
) -> dict[str, set[str]]:
    """Chunk ids this retriever contributed to the pool, per normalized query."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    pooled: dict[str, set[str]] = {}
    for query_key, entry in data["queries"].items():
        ids = {
            str(source["chunk_id"])
            for annotation in entry["annotations"].values()
            for source in annotation.get("sources", [])
            if source["retriever"] == retriever
            and source["rank"] <= max_rank
            and source.get("chunk_id") is not None
        }
        pooled[normalize_query(query_key)] = ids
    return pooled


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retriever", choices=sorted(POOL_ARMS), default="qwen")
    args = parser.parse_args()

    qrels = load_graded_qrels(paths.ANNOTATIONS_PATH)
    pooled = find_pooled_chunk_ids(paths.ANNOTATIONS_PATH, args.retriever, POOL_DEPTH)
    retriever = HybridRetriever(
        RetrievalConfig(arms=(replace(POOL_ARMS[args.retriever], depth=POOL_DEPTH),))
    )

    checked = 0
    failures: list[str] = []
    coverage: list[float] = []
    for query_key, qrel in sorted(qrels.items()):
        rows = await retriever.retrieve(qrel.query_text, top_k=POOL_DEPTH)
        matched = {str(row["id"]) for row in rows if lookup_gain(qrel, row) is not None}
        checked += len(pooled[query_key])
        for chunk_id in sorted(pooled[query_key] - matched):
            failures.append(f"{query_key}: {chunk_id}")
        if rows:
            coverage.append(len(matched) / len(rows))

    print(
        f"judgments contributed by {args.retriever} at rank <= {POOL_DEPTH}: {checked}"
    )
    print(
        f"mean judged coverage of the fresh top-{POOL_DEPTH}: "
        f"{sum(coverage) / len(coverage):.3f}"
    )
    if failures:
        print(f"\nFAILED — {len(failures)} judgments did not join back:")
        for failure in failures[:20]:
            print(f"  {failure}")
        raise SystemExit(1)
    print("OK — every pooled judgment joined back onto a fresh result.")


if __name__ == "__main__":
    asyncio.run(main())
