"""Why a run scores what it does, and what changed between two runs.

uv run python -m evals.retrieval.diagnose <run_id>            # worst queries first
uv run python -m evals.retrieval.diagnose <run_a> <run_b>     # per-query deltas
"""

import argparse
import json
from pathlib import Path
from typing import Any

from evals.retrieval import paths

METRIC = "ndcg@10"


def load_per_query(run_id: str, runs_dir: Path) -> list[dict[str, Any]]:
    with open(runs_dir / run_id / "per_query.json", encoding="utf-8") as f:
        return json.load(f)


def find_annotated(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r["kind"] == "annotated"]


def format_positions(record: dict[str, Any]) -> str:
    """Where each judged positive landed, e.g. '1,4,miss(2)'."""
    found = [str(p["rank"]) for p in record["positives"] if p["rank"] is not None]
    missed = sum(1 for p in record["positives"] if p["rank"] is None)
    parts = found or []
    if missed:
        parts = parts + [f"miss({missed})"]
    return ",".join(parts) or "-"


def count_arm_contributions(record: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in record["results"]:
        for arm in row.get("arms", {}):
            counts[arm] = counts.get(arm, 0) + 1
    return counts


def format_arms(counts: dict[str, int]) -> str:
    return " ".join(f"{arm}:{count}" for arm, count in sorted(counts.items())) or "-"


def compute_deltas(
    before: list[dict[str, Any]], after: list[dict[str, Any]], metric: str = METRIC
) -> list[dict[str, Any]]:
    """Per-query metric change, biggest regression first."""
    before_by_key = {r["query_key"]: r for r in before}
    deltas = []
    for record in after:
        previous = before_by_key.get(record["query_key"])
        if previous is None or metric not in record["metrics"]:
            continue
        deltas.append(
            {
                "query": record["query"],
                "query_key": record["query_key"],
                "kind": record["kind"],
                "split": record["split"],
                "before": previous["metrics"][metric],
                "after": record["metrics"][metric],
                "delta": record["metrics"][metric] - previous["metrics"][metric],
            }
        )
    return sorted(deltas, key=lambda d: d["delta"])


def diff_results(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> dict[str, list[Any]]:
    """Which chunks entered, left, or moved between two rankings."""
    before_ranks = {row["id"]: row["rank"] for row in before}
    after_ranks = {row["id"]: row["rank"] for row in after}
    gained = [row for row in after if row["id"] not in before_ranks]
    lost = [row for row in before if row["id"] not in after_ranks]
    moved = [
        (row["id"], before_ranks[row["id"]], row["rank"])
        for row in after
        if row["id"] in before_ranks and before_ranks[row["id"]] != row["rank"]
    ]
    return {"gained": gained, "lost": lost, "moved": moved}


def report_run(run_id: str, runs_dir: Path) -> None:
    records = find_annotated(load_per_query(run_id, runs_dir))
    records.sort(key=lambda r: (r["metrics"][METRIC], r["query"]))
    print(f"run {run_id} — annotated queries, worst first\n")
    print(
        f"{'split':<6} {'ndcg@10':>7} {'p@10':>6} {'rec@10':>6} {'cov':>5} "
        f"{'pos@ranks':<24} {'arms':<18} query"
    )
    for record in records:
        metrics = record["metrics"]
        print(
            f"{record['split']:<6} {metrics['ndcg@10']:>7.3f} "
            f"{metrics['precision@10']:>6.3f} {metrics['recall@10']:>6.3f} "
            f"{metrics['judged_coverage@10']:>5.2f} "
            f"{format_positions(record):<24} "
            f"{format_arms(count_arm_contributions(record)):<18} {record['query']}"
        )
    unjudged = sum(1 for r in records for row in r["results"] if not row["judged"])
    print(f"\nunjudged rows in top-10 across annotated queries: {unjudged}")


def report_generated_misses(run_id: str, runs_dir: Path, limit: int) -> None:
    records = [r for r in load_per_query(run_id, runs_dir) if r["kind"] == "generated"]
    misses = [r for r in records if r["metrics"]["file_recall@10"] == 0.0]
    print(
        f"\ngenerated queries missing their source file: {len(misses)}/{len(records)}"
    )
    for record in misses[:limit]:
        print(f"  {record['split']:<6} {record['query']}")


def report_diff(run_a: str, run_b: str, runs_dir: Path, limit: int) -> None:
    before = load_per_query(run_a, runs_dir)
    after = load_per_query(run_b, runs_dir)
    deltas = compute_deltas(find_annotated(before), find_annotated(after))
    print(f"{run_a}  ->  {run_b}\n")
    print(f"{'split':<6} {'before':>7} {'after':>7} {'delta':>7}  query")
    for delta in deltas:
        print(
            f"{delta['split']:<6} {delta['before']:>7.3f} {delta['after']:>7.3f} "
            f"{delta['delta']:>+7.3f}  {delta['query']}"
        )

    movers = [d for d in deltas if abs(d["delta"]) > 1e-9]
    movers.sort(key=lambda d: abs(d["delta"]), reverse=True)
    before_by_key = {r["query_key"]: r for r in find_annotated(before)}
    after_by_key = {r["query_key"]: r for r in find_annotated(after)}
    for mover in movers[:limit]:
        key = mover["query_key"]
        diff = diff_results(before_by_key[key]["results"], after_by_key[key]["results"])
        print(f"\n{mover['query']}  ({mover['delta']:+.3f})")
        for row in diff["gained"]:
            print(f"  + rank {row['rank']:>2} gain {row['gain']}  {row['id']}")
        for row in diff["lost"]:
            print(f"  - rank {row['rank']:>2} gain {row['gain']}  {row['id']}")

    file_deltas = compute_deltas(
        [r for r in before if r["kind"] == "generated"],
        [r for r in after if r["kind"] == "generated"],
        metric="file_mrr@10",
    )
    changed = [d for d in file_deltas if abs(d["delta"]) > 1e-9]
    print(
        f"\ngenerated file-mrr@10: {len(changed)} queries changed, "
        f"mean delta {sum(d['delta'] for d in file_deltas) / max(len(file_deltas), 1):+.4f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("other_run_id", nargs="?")
    parser.add_argument("--runs-dir", type=Path, default=paths.RUNS_DIR)
    parser.add_argument("--limit", type=int, default=5, help="detail rows to expand")
    args = parser.parse_args()

    if args.other_run_id:
        report_diff(args.run_id, args.other_run_id, args.runs_dir, args.limit)
    else:
        report_run(args.run_id, args.runs_dir)
        report_generated_misses(args.run_id, args.runs_dir, args.limit)


if __name__ == "__main__":
    main()
