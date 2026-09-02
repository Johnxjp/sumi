from unittest import mock

import pytest

from src.tools.registry import ToolRegistry
from src.tools.search import (
    TOP_K,
    format_chunk,
    register_search_tools,
    search_notes,
    summarise_search_result,
)


def make_row(row_id: str, title: str = "Title") -> dict:
    return {
        "id": row_id,
        "text": f"text of {row_id}",
        "source": row_id.split("#")[0],
        "metadata": {"title": title},
        "score": 0.3,
        "arms": {"qwen": 1, "fts": 4},
    }


@mock.patch("src.tools.search.retrieve", autospec=True)
def test_search_notes_returns_chunks_in_rank_order(retrieve):
    retrieve.return_value = [make_row("a.md#0", "A"), make_row("b/c.md#2", "C")]

    result = search_notes("q")

    retrieve.assert_awaited_once_with("q", top_k=TOP_K)
    assert result == [
        {
            "rank": 1,
            "chunk_id": "a.md#0",
            "source": "a.md",
            "title": "A",
            "text": "text of a.md#0",
        },
        {
            "rank": 2,
            "chunk_id": "b/c.md#2",
            "source": "b/c.md",
            "title": "C",
            "text": "text of b/c.md#2",
        },
    ]


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [({"title": "T"}, "T"), ({}, ""), (None, "")],
)
def test_format_chunk_title(metadata, expected):
    row = {**make_row("a.md#0"), "metadata": metadata}
    assert format_chunk(1, row)["title"] == expected


@mock.patch("src.tools.search.retrieve", autospec=True)
def test_register_search_tools_routes_to_search_notes(retrieve):
    retrieve.return_value = [make_row("a.md#0")]
    reg = ToolRegistry()

    register_search_tools(reg)

    [schema] = reg.tools
    assert schema["function"]["name"] == "search_notes"
    assert schema["function"]["parameters"]["required"] == ["query"]
    assert reg.get_tool("search_notes")["summarise"] is summarise_search_result
    assert reg.call_tool("search_notes", {"query": "q"})[0]["chunk_id"] == "a.md#0"
    retrieve.assert_awaited_once_with("q", top_k=TOP_K)


def test_summarise_search_result_lists_every_chunk():
    chunks = [
        format_chunk(1, make_row("a.md#0", "A")),
        format_chunk(2, make_row("b/c.md#2", "C")),
    ]

    header, *lines = summarise_search_result({"query": "q"}, chunks).splitlines()

    assert header.startswith("search_notes('q') returned 2 chunks.")
    assert lines == ["1. A — a.md", "2. C — b/c.md"]
