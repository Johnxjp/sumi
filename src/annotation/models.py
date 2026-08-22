from typing import Any, Literal

from pydantic import BaseModel, Field


class RetrieverSource(BaseModel):
    retriever: str
    chunk_id: str | None
    rank: int
    score: float | None


class PooledChunk(BaseModel):
    chunk_key: str
    text: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sources: list[RetrieverSource]
    annotation: int | None = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=50)


class SearchResponse(BaseModel):
    query: str
    chunks: list[PooledChunk]
    retriever_errors: dict[str, str] = Field(default_factory=dict)


class AnnotateRequest(BaseModel):
    query: str
    chunk_key: str
    score: Literal[0, 1, 2]
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sources: list[RetrieverSource] = Field(default_factory=list)
