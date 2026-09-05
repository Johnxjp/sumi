"""Ground truth: graded human judgments and file-level generated queries."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.retrieval.metrics import GainScheme, apply_gain
from src.annotation.pooling import compute_chunk_key
from src.annotation.store import normalize_query
from src.notion.mirror import extract_page_id


@dataclass(frozen=True)
class GradedQuery:
    """Human judgments for one query.

    Judgments are made on deduplicated chunk text, so chunk_key is the unit of
    truth; chunk ids are the fast path for joining a retrieved row back to it.
    """

    query_text: str
    gain_by_chunk_key: dict[str, int]
    chunk_key_by_chunk_id: dict[str, str]

    @property
    def num_relevant(self) -> int:
        return sum(1 for gain in self.gain_by_chunk_key.values() if gain > 0)

    @property
    def positive_gains(self) -> list[int]:
        return [gain for gain in self.gain_by_chunk_key.values() if gain > 0]

    def get_chunk_id(self, chunk_key: str) -> str | None:
        """A representative id for a judgment, for reporting missed positives."""
        ids = sorted(
            chunk_id
            for chunk_id, key in self.chunk_key_by_chunk_id.items()
            if key == chunk_key
        )
        return ids[0] if ids else None


@dataclass(frozen=True)
class FileQuery:
    """A generated query and the note it was generated from.

    `source` is what a retrieved chunk's `source` column must equal for the
    query to count as answered: the note's Notion page id.
    """

    query: str
    source: str
    has_page_id: bool = True


def load_graded_qrels(
    path: Path, gain_scheme: GainScheme = "exponential"
) -> dict[str, GradedQuery]:
    """Read annotations.json into qrels keyed by normalized query text."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    qrels: dict[str, GradedQuery] = {}
    for query_key, entry in data["queries"].items():
        gain_by_chunk_key: dict[str, int] = {}
        chunk_key_by_chunk_id: dict[str, str] = {}
        for chunk_key, annotation in entry["annotations"].items():
            gain_by_chunk_key[chunk_key] = apply_gain(
                int(annotation["score"]), gain_scheme
            )
            for source in annotation.get("sources", []):
                chunk_id = source.get("chunk_id")
                if chunk_id is not None:
                    chunk_key_by_chunk_id[str(chunk_id)] = chunk_key
        qrels[normalize_query(query_key)] = GradedQuery(
            query_text=entry.get("query_text", query_key),
            gain_by_chunk_key=gain_by_chunk_key,
            chunk_key_by_chunk_id=chunk_key_by_chunk_id,
        )
    return qrels


def match_chunk_key(qrel: GradedQuery, row: dict[str, Any]) -> str | None:
    """The judgment a retrieved row belongs to, or None if never judged.

    Chunk ids match across tables by construction; hashing the text is the
    fallback for a retriever whose ids differ (e.g. the BreadBowl index).
    """
    chunk_id = row.get("id")
    if chunk_id is not None:
        chunk_key = qrel.chunk_key_by_chunk_id.get(str(chunk_id))
        if chunk_key is not None:
            return chunk_key
    text = row.get("text")
    if isinstance(text, str) and text:
        chunk_key = compute_chunk_key(text, "eval", None)
        if chunk_key in qrel.gain_by_chunk_key:
            return chunk_key
    return None


def lookup_gain(qrel: GradedQuery, row: dict[str, Any]) -> int | None:
    chunk_key = match_chunk_key(qrel, row)
    return None if chunk_key is None else qrel.gain_by_chunk_key[chunk_key]


def load_file_queries(path: Path) -> list[FileQuery]:
    """Read the generated query set, mapping each note's file name to its page id.

    The queries were generated from the export and record the file they came
    from. Every such file name ends in the note's 32-character Notion page id,
    which is what chunks are now keyed by, so no data file has to be rewritten.
    One exported file is an uploaded attachment rather than a page and has no
    id; its query keeps the file name, can never match a chunk, and is counted
    in the run's `generated_without_page_id`.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    queries = []
    for item in data["queries"]:
        source_file = item["source_file"]
        page_id = extract_page_id(source_file)
        queries.append(
            FileQuery(
                query=item["query"],
                source=page_id or source_file,
                has_page_id=bool(page_id),
            )
        )
    return queries
