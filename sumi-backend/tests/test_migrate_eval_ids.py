import json

import pytest

from scripts.migrate_eval_ids import (
    find_chunk_id_for_text,
    find_judged_page_id,
    migrate_annotations,
)
from src.annotation.pooling import compute_chunk_key

PAGE = "336d52d026fc8076ade8f7b2612f1fef"
OTHER = "146d52d026fc8065a351fc6e2ea53f8b"
MAPPED = "the text that is still in the note"
SHIFTED = "the text that moved down the note"
GONE = "the text that was deleted in notion"


def key(text: str) -> str:
    return compute_chunk_key(text, "test", None)


@pytest.fixture
def annotations() -> dict:
    """Three judgments: one that maps, one that moved, one that is orphaned."""
    return {
        "version": 1,
        "queries": {
            "a query": {
                "query_text": "a query",
                "annotations": {
                    key(MAPPED): {
                        "score": 2,
                        "text": MAPPED,
                        "metadata": {
                            "title": "A",
                            "source": f"Journal/A {PAGE}.md",
                        },
                        "sources": [
                            {"retriever": "qwen", "chunk_id": f"Journal/A {PAGE}.md#0"}
                        ],
                    },
                    key(SHIFTED): {
                        "score": 1,
                        "text": SHIFTED,
                        "metadata": {"source": f"Journal/A {PAGE}.md"},
                        "sources": [
                            {"retriever": "qwen", "chunk_id": f"Journal/A {PAGE}.md#1"}
                        ],
                    },
                    key(GONE): {
                        "score": 2,
                        "text": GONE,
                        "metadata": {"source": f"Other {OTHER}.md"},
                        "sources": [
                            {"retriever": "qwen", "chunk_id": f"Other {OTHER}.md#0"}
                        ],
                    },
                },
            }
        },
    }


CHUNKS = {
    PAGE: [(f"{PAGE}#0", MAPPED), (f"{PAGE}#3", SHIFTED)],
    OTHER: [(f"{OTHER}#0", "something else entirely")],
}
PATHS = {PAGE: f"Journal/A {PAGE}.md", OTHER: f"Other {OTHER}.md"}


def test_a_judgment_is_pointed_at_the_chunk_that_holds_its_text(annotations):
    migrated, _ = migrate_annotations(annotations, CHUNKS, PATHS)

    judgment = migrated["queries"]["a query"]["annotations"][key(MAPPED)]
    assert judgment["sources"][0]["chunk_id"] == f"{PAGE}#0"
    assert judgment["metadata"]["source"] == PAGE
    assert judgment["metadata"]["path"] == f"Journal/A {PAGE}.md"


def test_text_that_moved_to_another_position_follows_it(annotations):
    migrated, _ = migrate_annotations(annotations, CHUNKS, PATHS)

    judgment = migrated["queries"]["a query"]["annotations"][key(SHIFTED)]
    assert judgment["sources"][0]["chunk_id"] == f"{PAGE}#3"


def test_a_judgment_whose_text_is_gone_is_left_alone_and_reported(annotations):
    migrated, report = migrate_annotations(annotations, CHUNKS, PATHS)

    judgment = migrated["queries"]["a query"]["annotations"][key(GONE)]
    assert judgment["sources"][0]["chunk_id"] == f"Other {OTHER}.md#0"
    assert judgment["metadata"]["source"] == f"Other {OTHER}.md"
    assert report.orphaned == [("a query", key(GONE))]


def test_the_report_counts_every_judgment(annotations):
    _, report = migrate_annotations(annotations, CHUNKS, PATHS)

    assert report.judgments == 3
    assert report.migrated == 2
    assert report.already_migrated == 0
    assert "orphaned (text is gone):  1" in report.describe()


def test_the_original_is_not_modified_in_place(annotations):
    before = json.dumps(annotations, sort_keys=True)

    migrate_annotations(annotations, CHUNKS, PATHS)

    assert json.dumps(annotations, sort_keys=True) == before


def test_running_twice_changes_nothing_the_second_time(annotations):
    once, _ = migrate_annotations(annotations, CHUNKS, PATHS)

    twice, report = migrate_annotations(once, CHUNKS, PATHS)

    assert twice == once
    assert report.migrated == 0
    assert report.already_migrated == 2


def test_a_judgment_with_no_page_id_anywhere_is_reported(annotations):
    annotations["queries"]["a query"]["annotations"][key(MAPPED)] = {
        "score": 2,
        "text": MAPPED,
        "metadata": {"source": "career-direction.md"},
        "sources": [{"retriever": "qwen", "chunk_id": "career-direction.md#0"}],
    }

    _, report = migrate_annotations(annotations, CHUNKS, PATHS)

    assert report.without_page_id == [key(MAPPED)]


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ({"sources": [{"chunk_id": f"Journal/A {PAGE}.md#0"}]}, PAGE),
        ({"sources": [{"chunk_id": f"{PAGE}#2"}]}, PAGE),
        ({"sources": [], "metadata": {"source": f"Journal/A {PAGE}.md"}}, PAGE),
        ({"sources": [{"chunk_id": "no-id.md#0"}]}, None),
        ({}, None),
    ],
    ids=[
        "from-an-export-path",
        "from-an-already-migrated-id",
        "from-the-metadata-when-there-are-no-sources",
        "no-id-in-the-path",
        "nothing-recorded",
    ],
)
def test_find_judged_page_id(annotation, expected):
    assert find_judged_page_id(annotation) == expected


def test_find_chunk_id_for_text_returns_none_when_the_text_is_gone():
    assert find_chunk_id_for_text(CHUNKS[OTHER], key(GONE)) is None


def test_find_chunk_id_ignores_whitespace_differences():
    chunks = [(f"{PAGE}#0", f"  {MAPPED}  ")]
    assert find_chunk_id_for_text(chunks, key(MAPPED)) == f"{PAGE}#0"
