from unittest import mock

import pytest

from src.retrieval.search_config import ACTIVE_CONFIG, ACTIVE_CONFIG_NAME
from src.tools.registry import ToolRegistry
from src.tools.search import (
    format_chunk,
    register_search_tools,
    search_notes,
    summarise_search_result,
)

PAGE_A = "336d52d026fc8076ade8f7b2612f1fef"
PAGE_C = "146d52d026fc8065a351fc6e2ea53f8b"


def make_row(row_id: str, title: str = "Title", path: str = "Journal/A.md") -> dict:
    return {
        "id": row_id,
        "text": f"text of {row_id}",
        "source": row_id.split("#")[0],
        "metadata": {"title": title, "path": path},
        "score": 0.3,
        "arms": {"qwen": 1, "fts": 4},
    }


@mock.patch("src.tools.search.retrieve", autospec=True)
def test_search_notes_returns_chunks_in_rank_order(retrieve):
    retrieve.return_value = [
        make_row(f"{PAGE_A}#0", "A", "Journal/A.md"),
        make_row(f"{PAGE_C}#2", "C", "Life OS/C.md"),
    ]

    result = search_notes("q")

    retrieve.assert_awaited_once_with("q", top_k=ACTIVE_CONFIG.top_k)
    assert result == [
        {
            "rank": 1,
            "chunk_id": f"{PAGE_A}#0",
            "page_id": PAGE_A,
            "path": "Journal/A.md",
            "title": "A",
            "text": f"text of {PAGE_A}#0",
        },
        {
            "rank": 2,
            "chunk_id": f"{PAGE_C}#2",
            "page_id": PAGE_C,
            "path": "Life OS/C.md",
            "title": "C",
            "text": f"text of {PAGE_C}#2",
        },
    ]


@pytest.mark.parametrize(
    ("metadata", "title", "path"),
    [
        ({"title": "T", "path": "p.md"}, "T", "p.md"),
        ({"title": "T"}, "T", ""),
        ({}, "", ""),
        (None, "", ""),
    ],
    ids=["both", "no-path", "empty-metadata", "no-metadata"],
)
def test_format_chunk_reads_title_and_path_from_metadata(metadata, title, path):
    row = {**make_row(f"{PAGE_A}#0"), "metadata": metadata}
    chunk = format_chunk(1, row)
    assert (chunk["title"], chunk["path"]) == (title, path)


@mock.patch("src.tools.search.retrieve", autospec=True)
def test_register_search_tools_routes_to_search_notes(retrieve):
    retrieve.return_value = [make_row(f"{PAGE_A}#0")]
    reg = ToolRegistry()

    register_search_tools(reg)

    [schema] = reg.tools
    assert schema["function"]["name"] == "search_notes"
    assert schema["function"]["parameters"]["required"] == ["query"]
    assert reg.get_tool("search_notes")["summarise"] is summarise_search_result
    assert reg.call_tool("search_notes", {"query": "q"})[0]["chunk_id"] == f"{PAGE_A}#0"
    retrieve.assert_awaited_once_with("q", top_k=ACTIVE_CONFIG.top_k)


def test_summarise_search_result_lists_every_chunk_by_path():
    chunks = [
        format_chunk(1, make_row(f"{PAGE_A}#0", "A", "Journal/A.md")),
        format_chunk(2, make_row(f"{PAGE_C}#2", "C", "Life OS/C.md")),
    ]

    header, *lines = summarise_search_result({"query": "q"}, chunks).splitlines()

    assert header.startswith("search_notes('q') returned 2 chunks.")
    assert lines == ["1. A — Journal/A.md", "2. C — Life OS/C.md"]


@mock.patch("src.tools.search.retrieve", autospec=True)
def test_searching_writes_a_usage_record(retrieve):
    """Every search is logged, so real queries can be labelled later."""
    retrieve.return_value = [make_row(f"{PAGE_A}#0")]

    with mock.patch("src.tools.search.record_search", autospec=True) as record:
        chunks = search_notes("napoleon leadership")

    record.assert_called_once_with("napoleon leadership", chunks, ACTIVE_CONFIG_NAME)
