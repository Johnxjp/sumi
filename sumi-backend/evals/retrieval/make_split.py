"""Generate the train/val split file.

Run once: `uv run python -m evals.retrieval.make_split`. Regenerating with a
different seed invalidates every recorded run comparison, hence --force.
"""

import argparse

from evals.retrieval import paths
from evals.retrieval.qrels import load_file_queries, load_graded_qrels
from evals.retrieval.split import build_split, save_split
from src.annotation.store import normalize_query

DEFAULT_SEED = 17


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing split"
    )
    args = parser.parse_args()

    if paths.SPLIT_PATH.exists() and not args.force:
        raise SystemExit(
            f"{paths.SPLIT_PATH} already exists; pass --force to overwrite "
            "(this invalidates comparisons against existing runs)."
        )

    annotated = sorted(load_graded_qrels(paths.ANNOTATIONS_PATH))
    generated = sorted(
        {
            normalize_query(q.query)
            for q in load_file_queries(paths.GENERATED_QUERIES_PATH)
        }
    )
    split = build_split(
        {"annotated": annotated, "generated": generated}, seed=args.seed
    )
    save_split(paths.SPLIT_PATH, split)
    print(
        f"wrote {paths.SPLIT_PATH}: {len(split.train)} train / {len(split.val)} val "
        f"(annotated {len(annotated)}, generated {len(generated)}, seed {args.seed})"
    )


if __name__ == "__main__":
    main()
