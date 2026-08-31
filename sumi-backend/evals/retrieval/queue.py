"""Queue of retrieved-but-unjudged chunks, for later human labeling.

Runs never block on missing judgments: anything a run surfaced that the pool
has never seen is appended here, deduplicated across runs, and picked up in
the annotation UI whenever the user labels next.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.retrieval.qrels import GradedQuery, lookup_gain
from src.annotation.pooling import compute_chunk_key


@dataclass(frozen=True)
class UnjudgedCandidate:
    query_key: str
    query_text: str
    rank: int
    row: dict[str, Any]


def _load_queue(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_queue(path: Path, data: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise


def is_judged(
    qrels: dict[str, GradedQuery], query_key: str, row: dict[str, Any]
) -> bool:
    qrel = qrels.get(query_key)
    return qrel is not None and lookup_gain(qrel, row) is not None


def append_unjudged(
    path: Path,
    qrels: dict[str, GradedQuery],
    run_id: str,
    entries: list[UnjudgedCandidate],
) -> int:
    """Merge this run's unjudged pairs into the queue, returning the new count."""
    queue = _load_queue(path)
    queue = {
        key: item
        for key, item in queue.items()
        if not is_judged(
            qrels, item["query_key"], {"id": item["chunk_id"], "text": item["text"]}
        )
    }
    now = datetime.now(UTC).isoformat()
    added = 0
    for entry in entries:
        if is_judged(qrels, entry.query_key, entry.row):
            continue
        chunk_id = entry.row.get("id")
        key = f"{entry.query_key}||{chunk_id}"
        item = queue.get(key)
        if item is None:
            text = entry.row.get("text")
            metadata = entry.row.get("metadata") or {}
            queue[key] = {
                "query_key": entry.query_key,
                "query": entry.query_text,
                "chunk_id": chunk_id,
                "chunk_key": compute_chunk_key(text, "eval", chunk_id),
                "text": text,
                "source": entry.row.get("source"),
                "title": metadata.get("title"),
                "best_rank": entry.rank,
                "runs": [run_id],
                "first_seen_at": now,
            }
            added += 1
        else:
            item["best_rank"] = min(item["best_rank"], entry.rank)
            if run_id not in item["runs"]:
                item["runs"].append(run_id)
    _save_queue(path, queue)
    return added
