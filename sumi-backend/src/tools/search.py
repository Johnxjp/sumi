"""Expose hybrid retrieval over the notes to the agent as a tool."""

import asyncio
from typing import Any

from src.retrieval.retrieve import retrieve
from src.tools.registry import ToolRegistry, registry

# The depth every retrieval eval number is reported at.
TOP_K = 10

SEARCH_NOTES_SCHEMA = {
    "name": "search_notes",
    "description": (
        "Searches the user's notes by meaning and by keywords and returns the "
        f"{TOP_K} best-matching chunks. A chunk is one passage of at most 2,000 "
        "characters cut from a note; it is not the whole note. The result is a "
        "JSON list ordered by rank, where rank 1 is the best match. Each item "
        "has: 'rank'; 'chunk_id', the chunk's identifier, formed as the note's "
        "path, then '#', then the chunk's position within that note (0 = first "
        "chunk); 'source', the note's path, which you can pass to read_file to "
        "read the entire note; 'title', the note's title; 'text', the full "
        f"content of the chunk. The {TOP_K} results are always the closest "
        "matches available, with no relevance cut-off, so some may not be "
        "relevant: judge each chunk by its content. Use this first for any "
        "question about what the notes say. Use grep only to find an exact "
        "title or string, and read_file to see the whole note a chunk came from."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for, in natural language.",
            }
        },
        "required": ["query"],
    },
}


def format_chunk(rank: int, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": rank,
        "chunk_id": row["id"],
        "source": row["source"],
        "title": (row.get("metadata") or {}).get("title", ""),
        "text": row["text"],
    }


def search_notes(query: str) -> list[dict[str, Any]]:
    rows = asyncio.run(retrieve(query, top_k=TOP_K))
    return [format_chunk(rank, row) for rank, row in enumerate(rows, start=1)]


def summarise_search_result(
    arguments: dict[str, Any], chunks: list[dict[str, Any]]
) -> str:
    header = (
        f"search_notes({arguments['query']!r}) returned {len(chunks)} chunks. "
        "Their text was removed from the history; call read_file with a source "
        "path to read a note, or search again."
    )
    lines = [
        f"{chunk['rank']}. {chunk['title']} — {chunk['source']}" for chunk in chunks
    ]
    return "\n".join([header, *lines])


def register_search_tools(reg: ToolRegistry = registry) -> None:
    reg.register_tool(
        "search_notes",
        search_notes,
        SEARCH_NOTES_SCHEMA,
        summarise=summarise_search_result,
    )
