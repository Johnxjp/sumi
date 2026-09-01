"""Reciprocal rank fusion of several ranked candidate lists."""

from typing import Any


def fuse_rrf(
    ranked: dict[str, list[dict[str, Any]]],
    k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Merge per-arm rankings by summing weight / (k + rank), best first.

    Rows are deduplicated by "id": every table is built from the same chunker
    with ids "{source}#{chunk_index}", so equal ids mean the same chunk text.
    The fused row keeps the first arm's text and metadata, replaces score with
    the RRF score, and records the rank each arm gave it under "arms".
    """
    fused: dict[str, dict[str, Any]] = {}
    for arm, rows in ranked.items():
        weight = 1.0 if weights is None else weights.get(arm, 1.0)
        for rank, row in enumerate(rows, start=1):
            entry = fused.get(row["id"])
            if entry is None:
                entry = {**row, "score": 0.0, "arms": {}}
                fused[row["id"]] = entry
            entry["score"] += weight / (k + rank)
            entry["arms"][arm] = rank
    return sorted(fused.values(), key=lambda row: (-row["score"], row["id"]))
