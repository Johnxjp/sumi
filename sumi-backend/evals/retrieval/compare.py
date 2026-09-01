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


def format_metric(block: dict[str, Any], name: str, width: int) -> str:
    """A dash where a run has no value — an older run predating the metric,
    or a query set it skipped — so it is never read as a score of zero."""
    value = block.get(name)
    if value is None or not block.get("num_queries"):
        return f"{'-':>{width}}"
    return f"{value:>{width}.3f}"


def format_row(run: dict[str, Any]) -> str:
    cells = []
    for split in ("train", "val"):
        annotated, generated = run[split]["annotated"], run[split]["generated"]
        cells.append(
            f"{format_metric(annotated, 'ndcg@10', 7)} "
            f"{format_metric(annotated, 'ndcg@10_condensed', 6)} "
            f"{format_metric(annotated, 'precision@10', 6)} "
            f"{format_metric(generated, 'file_recall@10', 6)} "
            f"{format_metric(generated, 'file_mrr@10', 6)}"
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
