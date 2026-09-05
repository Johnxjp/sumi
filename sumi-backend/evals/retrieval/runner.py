"""Run one retrieval configuration over both query sets and record the result."""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tqdm import tqdm

from evals.retrieval import paths
from evals.retrieval.metrics import (
    GainScheme,
    compute_mrr,
    compute_ndcg,
    compute_precision,
    compute_recall,
)
from evals.retrieval.qrels import (
    FileQuery,
    GradedQuery,
    load_file_queries,
    load_graded_qrels,
    lookup_gain,
    match_chunk_key,
)
from evals.retrieval.queue import UnjudgedCandidate, append_unjudged
from evals.retrieval.split import Split, load_split
from src.annotation.store import normalize_query
from src.notion.mirror import extract_page_id
from src.retrieval.retrieve import HybridRetriever
from src.retrieval.search_config import RetrievalConfig

K = 10
SNIPPET_CHARS = 240


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    retrieval: RetrievalConfig
    gain_scheme: GainScheme = "exponential"
    notes: str = ""


@dataclass
class QueryRecord:
    query: str
    query_key: str
    kind: str
    split: str
    metrics: dict[str, float]
    results: list[dict[str, Any]]
    positives: list[dict[str, Any]] = field(default_factory=list)


def build_result_rows(
    rows: list[dict[str, Any]], qrel: GradedQuery | None
) -> list[dict[str, Any]]:
    """Ranked results trimmed for storage, each tagged with its judgment."""
    records = []
    for rank, row in enumerate(rows, start=1):
        gain = None if qrel is None else lookup_gain(qrel, row)
        text = row.get("text") or ""
        metadata = row.get("metadata") or {}
        records.append(
            {
                "rank": rank,
                "id": row.get("id"),
                "source": row.get("source"),
                # The note's file, so `diagnose` can name a result rather than
                # printing a page id. Absent on the export-built tables.
                "path": metadata.get("path"),
                "title": metadata.get("title"),
                "score": row.get("score"),
                "arms": row.get("arms", {}),
                "gain": gain,
                "judged": gain is not None,
                "snippet": text[:SNIPPET_CHARS],
            }
        )
    return records


def score_annotated(qrel: GradedQuery, rows: list[dict[str, Any]]) -> dict[str, float]:
    """Score one ranking both ways an incomplete judgment set allows.

    ndcg@10 counts an unjudged chunk as irrelevant, which is the honest
    pessimistic reading but punishes a configuration for surfacing chunks
    the annotation pool never contained. ndcg@10_condensed drops unjudged
    chunks from the ranking instead — the standard condensed-list treatment
    — so two configurations can be compared on the chunks both were judged
    on. judged_coverage@10 says how far apart the two readings can be.
    """
    gains = [lookup_gain(qrel, row) for row in rows]
    scored = [0 if gain is None else gain for gain in gains]
    condensed = [gain for gain in gains if gain is not None]
    judged = [gain is not None for gain in gains][:K]
    return {
        "ndcg@10": compute_ndcg(scored, qrel.positive_gains, K),
        "ndcg@10_condensed": compute_ndcg(condensed, qrel.positive_gains, K),
        "ndcg@5": compute_ndcg(scored, qrel.positive_gains, 5),
        "recall@10": compute_recall(scored, qrel.num_relevant, K),
        "mrr@10": compute_mrr(scored, K),
        "precision@10": compute_precision(scored, K),
        "judged_coverage@10": sum(judged) / len(judged) if judged else 0.0,
    }


def find_positive_ranks(
    qrel: GradedQuery, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every judged positive with the rank it was found at, or None if missed."""
    rank_by_key = {}
    for rank, row in enumerate(rows, start=1):
        chunk_key = match_chunk_key(qrel, row)
        if chunk_key is not None and chunk_key not in rank_by_key:
            rank_by_key[chunk_key] = rank
    return [
        {
            "chunk_key": chunk_key,
            "chunk_id": qrel.get_chunk_id(chunk_key),
            "gain": gain,
            "rank": rank_by_key.get(chunk_key),
        }
        for chunk_key, gain in sorted(qrel.gain_by_chunk_key.items())
        if gain > 0
    ]


def score_generated(
    file_query: FileQuery, rows: list[dict[str, Any]]
) -> dict[str, float]:
    """A hit is any chunk of the note the query was generated from.

    The note is named by its Notion page id, which is in a chunk's source
    whichever corpus answered: the frozen export corpus stores a file path
    ending in the id, the synced corpus stores the id itself.
    """
    hits = [
        1 if extract_page_id(str(row.get("source") or "")) == file_query.source else 0
        for row in rows
    ]
    return {
        "file_recall@10": 1.0 if any(hits[:K]) else 0.0,
        "file_mrr@10": compute_mrr(hits, K),
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate(records: list[QueryRecord], split_name: str) -> dict[str, Any]:
    """Mean metrics for one split, annotated and generated reported apart."""
    annotated = [r for r in records if r.kind == "annotated" and r.split == split_name]
    scored = [r for r in annotated if r.metrics["num_relevant"] > 0]
    generated = [r for r in records if r.kind == "generated" and r.split == split_name]
    block: dict[str, Any] = {
        "annotated": {
            name: mean([r.metrics[name] for r in scored])
            for name in (
                "ndcg@10",
                "ndcg@10_condensed",
                "ndcg@5",
                "recall@10",
                "mrr@10",
                "precision@10",
                "judged_coverage@10",
            )
        }
    }
    block["annotated"]["num_queries"] = len(scored)
    block["annotated"]["excluded_zero_positive"] = len(annotated) - len(scored)
    block["generated"] = {
        "file_recall@10": mean([r.metrics["file_recall@10"] for r in generated]),
        "file_mrr@10": mean([r.metrics["file_mrr@10"] for r in generated]),
        "num_queries": len(generated),
    }
    return block


def split_of(split: Split, query_key: str) -> str:
    if query_key in split.train:
        return "train"
    if query_key in split.val:
        return "val"
    return "unassigned"


def persist_run(
    run_dir: Path,
    config: ExperimentConfig,
    metrics: dict[str, Any],
    records: list[QueryRecord],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(asdict(config), f, ensure_ascii=False, indent=2)
    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    with open(run_dir / "per_query.json", "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, ensure_ascii=False, indent=2)


async def run_experiment(
    config: ExperimentConfig,
    retriever: HybridRetriever | None = None,
    annotated_only: bool = False,
    runs_dir: Path = paths.RUNS_DIR,
    queue_path: Path = paths.UNJUDGED_QUEUE_PATH,
) -> dict[str, Any]:
    """Score one configuration on every query and write the run to disk."""
    qrels = load_graded_qrels(paths.ANNOTATIONS_PATH, config.gain_scheme)
    split = load_split(paths.SPLIT_PATH)
    file_queries = (
        [] if annotated_only else load_file_queries(paths.GENERATED_QUERIES_PATH)
    )
    if retriever is None:
        retriever = HybridRetriever(config.retrieval)

    records: list[QueryRecord] = []
    candidates: list[UnjudgedCandidate] = []
    for query_key, qrel in tqdm(sorted(qrels.items()), desc="annotated"):
        rows = await retriever.retrieve(qrel.query_text, top_k=K)
        metrics = score_annotated(qrel, rows)
        metrics["num_relevant"] = qrel.num_relevant
        records.append(
            QueryRecord(
                query=qrel.query_text,
                query_key=query_key,
                kind="annotated",
                split=split_of(split, query_key),
                metrics=metrics,
                results=build_result_rows(rows, qrel),
                positives=find_positive_ranks(qrel, rows),
            )
        )
        candidates.extend(
            UnjudgedCandidate(
                query_key=query_key, query_text=qrel.query_text, rank=rank, row=row
            )
            for rank, row in enumerate(rows, start=1)
            if lookup_gain(qrel, row) is None
        )

    for file_query in tqdm(file_queries, desc="generated"):
        rows = await retriever.retrieve(file_query.query, top_k=K)
        query_key = normalize_query(file_query.query)
        records.append(
            QueryRecord(
                query=file_query.query,
                query_key=query_key,
                kind="generated",
                split=split_of(split, query_key),
                metrics=score_generated(file_query, rows),
                results=build_result_rows(rows, None),
            )
        )

    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{config.name}"
    queued = append_unjudged(queue_path, qrels, run_id, candidates)
    metrics = {
        "run_id": run_id,
        "name": config.name,
        "created_at": datetime.now(UTC).isoformat(),
        "notes": config.notes,
        "train": aggregate(records, "train"),
        "val": aggregate(records, "val"),
        "unjudged_queued": queued,
        # Generated queries whose note has no Notion page id, so they can never
        # be scored as a hit. One exported file is an attachment, not a page.
        "generated_without_page_id": sum(
            1 for file_query in file_queries if not file_query.has_page_id
        ),
    }
    persist_run(runs_dir / run_id, config, metrics, records)
    return metrics
