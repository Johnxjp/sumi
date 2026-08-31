"""Table of every recorded run: `uv run python -m evals.retrieval.compare`."""

import argparse
import json
from pathlib import Path
from typing import Any

from evals.retrieval import paths

HEADER = (
    f"{'run_id':<40} {'train':>38}  {'val':>38}\n"
    f"{'':<40} {'ndcg@10':>7} {'cond':>6} {'p@10':>6} {'f-rec':>6} {'f-mrr':>6}  "
    f"{'ndcg@10':>7} {'cond':>6} {'p@10':>6} {'f-rec':>6} {'f-mrr':>6}"
)


def load_runs(runs_dir: Path) -> list[dict[str, Any]]:
    runs = []
    for metrics_path in sorted(runs_dir.glob("*/metrics.json")):
        with open(metrics_path, encoding="utf-8") as f:
            runs.append(json.load(f))
    return runs


def format_row(run: dict[str, Any]) -> str:
    cells = []
    for split in ("train", "val"):
        block = run[split]
        cells.append(
            f"{block['annotated']['ndcg@10']:>7.3f} "
            f"{block['annotated'].get('ndcg@10_condensed', 0.0):>6.3f} "
            f"{block['annotated']['precision@10']:>6.3f} "
            f"{block['generated']['file_recall@10']:>6.3f} "
            f"{block['generated']['file_mrr@10']:>6.3f}"
        )
    return f"{run['run_id']:<40} {cells[0]}  {cells[1]}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=paths.RUNS_DIR)
    args = parser.parse_args()

    runs = load_runs(args.runs_dir)
    if not runs:
        raise SystemExit(f"no runs in {args.runs_dir}")
    runs.sort(key=lambda run: run["train"]["annotated"]["ndcg@10"], reverse=True)
    print(HEADER)
    for run in runs:
        print(format_row(run))


if __name__ == "__main__":
    main()
