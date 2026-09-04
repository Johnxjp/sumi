"""Expose hybrid retrieval over the notes to the agent as a tool."""

import asyncio
from typing import Any

from src.retrieval.retrieve import retrieve
from src.retrieval.search_config import ACTIVE_CONFIG
from src.tools.registry import ToolRegistry, registry

SEARCH_NOTES_SCHEMA = {
    "name": "search_notes",
    "description": (
        "Searches the notes with hybrid semantic and lexical search and returns "
        "the most relevant matches. Matches are chunks: sections of a note, "
        "bounded by a character limit, not whole notes. "
        "Use this when the user's request needs an answer to a question or "
        "information found by similarity. Use grep when you need to find "
        "specific terms in a title or note, and read_file to see a whole note. "
        "Phrase the query with the words the note itself would contain and leave "
        "out words that are not core to the request: 'What did I write in my "
        "personal vision?' becomes 'personal vision', which is what the note "
        "contains. "
        f"Returns a JSON list of the {ACTIVE_CONFIG.top_k} closest chunks, most "
        "relevant first. Each has rank, chunk_id, page_id (the note's id), path "
        "(the note's file, which read_file accepts), title and text. Not all are "
        "relevant to the query, so judge each by its content before answering."
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
    """One chunk as the model sees it.

    `page_id` is the chunk's note; `path` is that note's file in the notes
    folder, which is what read_file takes. They are separate fields because a
    chunk's `source` column holds a Notion page id, not a path.
    """
    metadata = row.get("metadata") or {}
    return {
        "rank": rank,
        "chunk_id": row["id"],
        "page_id": row["source"],
        "path": metadata.get("path", ""),
        "title": metadata.get("title", ""),
        "text": row["text"],
    }


def search_notes(query: str) -> list[dict[str, Any]]:
    rows = asyncio.run(retrieve(query, top_k=ACTIVE_CONFIG.top_k))
    return [format_chunk(rank, row) for rank, row in enumerate(rows, start=1)]


def summarise_search_result(
    arguments: dict[str, Any], chunks: list[dict[str, Any]]
) -> str:
    header = (
        f"search_notes({arguments['query']!r}) returned {len(chunks)} chunks. "
        "Their text was removed from the history; call read_file with a chunk's "
        "path to read a note, or search again."
    )
    lines = [f"{chunk['rank']}. {chunk['title']} — {chunk['path']}" for chunk in chunks]
    return "\n".join([header, *lines])


def register_search_tools(reg: ToolRegistry = registry) -> None:
    reg.register_tool(
        "search_notes",
        search_notes,
        SEARCH_NOTES_SCHEMA,
        summarise=summarise_search_result,
    )
