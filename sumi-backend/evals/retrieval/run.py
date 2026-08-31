"""Run a registered experiment: `uv run python -m evals.retrieval.run <name>`."""

import argparse
import asyncio

from evals.retrieval.experiments import EXPERIMENTS
from evals.retrieval.runner import run_experiment


def format_block(name: str, block: dict) -> str:
    annotated = block["annotated"]
    generated = block["generated"]
    return (
        f"{name:<6} ndcg@10 {annotated['ndcg@10']:.3f}"
        f"  condensed {annotated['ndcg@10_condensed']:.3f}"
        f"  recall@10 {annotated['recall@10']:.3f}  mrr@10 {annotated['mrr@10']:.3f}"
        f"  p@10 {annotated['precision@10']:.3f}"
        f"  judged {annotated['judged_coverage@10']:.3f}"
        f"  (n={annotated['num_queries']}, excluded={annotated['excluded_zero_positive']})"
        f"\n{'':<6} file-recall@10 {generated['file_recall@10']:.3f}"
        f"  file-mrr@10 {generated['file_mrr@10']:.3f} (n={generated['num_queries']})"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=sorted(EXPERIMENTS))
    parser.add_argument(
        "--annotated-only",
        action="store_true",
        help="skip the generated query set for a faster iteration loop",
    )
    args = parser.parse_args()

    config = EXPERIMENTS[args.experiment]
    metrics = await run_experiment(config, annotated_only=args.annotated_only)
    print(f"\nrun {metrics['run_id']}")
    print(format_block("train", metrics["train"]))
    print(format_block("val", metrics["val"]))
    print(f"unjudged queued: {metrics['unjudged_queued']}")


if __name__ == "__main__":
    asyncio.run(main())
