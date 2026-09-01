"""Pool results from several retrievers, deduplicated by normalized chunk text."""

import hashlib
from typing import Any

from pydantic import BaseModel

from src.annotation.models import PooledChunk, RetrieverSource

ID_FIELDS = ("chunk_id", "doc_id", "id")
TEXT_FIELDS = ("text", "chunk", "content")
SCORE_FIELDS = ("score", "similarity")
METADATA_FIELDS = ("metadata", "doc_metadata")


class ParsedResult(BaseModel):
    chunk_key: str
    chunk_id: str | None
    text: str | None
    score: float | None
    metadata: dict[str, Any]


def compute_chunk_key(text: str | None, retriever: str, chunk_id: str | None) -> str:
    if text:
        normalized = " ".join(text.split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"noid:{retriever}:{chunk_id}"


def _first_present(raw: dict[str, Any], fields: tuple[str, ...]) -> Any:
    for field in fields:
        if field in raw and raw[field] is not None:
            return raw[field]
    return None


def parse_result(raw: dict[str, Any], retriever: str) -> ParsedResult:
    chunk_id = _first_present(raw, ID_FIELDS)
    text = _first_present(raw, TEXT_FIELDS)
    score = _first_present(raw, SCORE_FIELDS)
    metadata = _first_present(raw, METADATA_FIELDS)
    if not isinstance(metadata, dict):
        metadata = {}
    source = raw.get("source")
    if isinstance(source, str) and "source" not in metadata:
        metadata = {**metadata, "source": source}
    return ParsedResult(
        chunk_key=compute_chunk_key(
            text if isinstance(text, str) else None,
            retriever,
            str(chunk_id) if chunk_id is not None else None,
        ),
        chunk_id=str(chunk_id) if chunk_id is not None else None,
        text=text if isinstance(text, str) else None,
        score=float(score) if isinstance(score, (int, float)) else None,
        metadata=metadata,
    )


def pool_results(
    per_retriever: dict[str, list[dict[str, Any]]],
    existing: dict[str, int],
) -> list[PooledChunk]:
    pooled: dict[str, PooledChunk] = {}
    for retriever, results in per_retriever.items():
        for rank, raw in enumerate(results, start=1):
            parsed = parse_result(raw, retriever)
            source = RetrieverSource(
                retriever=retriever,
                chunk_id=parsed.chunk_id,
                rank=rank,
                score=parsed.score,
            )
            chunk = pooled.get(parsed.chunk_key)
            if chunk is None:
                pooled[parsed.chunk_key] = PooledChunk(
                    chunk_key=parsed.chunk_key,
                    text=parsed.text,
                    metadata=parsed.metadata,
                    sources=[source],
                    annotation=existing.get(parsed.chunk_key),
                )
            else:
                chunk.sources.append(source)

    return sorted(
        pooled.values(),
        key=lambda c: (min(s.rank for s in c.sources), c.chunk_key),
    )
