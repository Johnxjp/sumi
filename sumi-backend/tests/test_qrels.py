import json

import pytest

from evals.retrieval.qrels import (
    load_file_queries,
    load_graded_qrels,
    lookup_gain,
    match_chunk_key,
)
from src.annotation.pooling import compute_chunk_key

TEXT = "Napoleon on leadership"
CHUNK_KEY = compute_chunk_key(TEXT, "qwen", "notes/a.md#0")


@pytest.fixture
def annotations_path(tmp_path):
    path = tmp_path / "annotations.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "queries": {
                    "  What  Does Napoleon Say? ": {
                        "query_text": "What  Does Napoleon Say?",
                        "annotations": {
                            CHUNK_KEY: {
                                "score": 2,
                                "text": TEXT,
                                "sources": [
                                    {"retriever": "qwen", "chunk_id": "notes/a.md#0"},
                                    {"retriever": "bge-m3", "chunk_id": "other#7"},
                                ],
                            },
                            "otherkey": {
                                "score": 0,
                                "text": "unrelated",
                                "sources": [
                                    {"retriever": "qwen", "chunk_id": "notes/b.md#0"}
                                ],
                            },
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_load_graded_qrels_keys_by_normalized_query(annotations_path):
    qrels = load_graded_qrels(annotations_path)
    assert list(qrels) == ["what does napoleon say?"]
    assert qrels["what does napoleon say?"].query_text == "What  Does Napoleon Say?"


def test_load_graded_qrels_collects_every_source_chunk_id(annotations_path):
    qrel = load_graded_qrels(annotations_path)["what does napoleon say?"]
    assert qrel.chunk_key_by_chunk_id == {
        "notes/a.md#0": CHUNK_KEY,
        "other#7": CHUNK_KEY,
        "notes/b.md#0": "otherkey",
    }


def test_load_graded_qrels_applies_the_gain_scheme(annotations_path):
    exponential = load_graded_qrels(annotations_path)["what does napoleon say?"]
    linear = load_graded_qrels(annotations_path, "linear")["what does napoleon say?"]
    assert exponential.gain_by_chunk_key[CHUNK_KEY] == 3
    assert linear.gain_by_chunk_key[CHUNK_KEY] == 2


def test_graded_query_summarises_its_positives(annotations_path):
    qrel = load_graded_qrels(annotations_path)["what does napoleon say?"]
    assert qrel.num_relevant == 1
    assert qrel.positive_gains == [3]
    assert qrel.get_chunk_id(CHUNK_KEY) == "notes/a.md#0"
    assert qrel.get_chunk_id("unknown") is None


@pytest.mark.parametrize(
    ("row", "expected_key", "expected_gain"),
    [
        ({"id": "notes/a.md#0", "text": "different text"}, CHUNK_KEY, 3),
        ({"id": "other#7", "text": ""}, CHUNK_KEY, 3),
        ({"id": "unknown#1", "text": f"  {TEXT}  "}, CHUNK_KEY, 3),
        ({"id": "notes/b.md#0", "text": "unrelated"}, "otherkey", 0),
        ({"id": "unknown#1", "text": "never seen"}, None, None),
        ({"id": None, "text": None}, None, None),
    ],
    ids=[
        "id-hit",
        "id-hit-from-another-retriever",
        "text-fallback",
        "judged-negative",
        "unjudged",
        "no-id-no-text",
    ],
)
def test_match_by_chunk_id_then_text(
    annotations_path, row, expected_key, expected_gain
):
    qrel = load_graded_qrels(annotations_path)["what does napoleon say?"]
    assert match_chunk_key(qrel, row) == expected_key
    assert lookup_gain(qrel, row) == expected_gain


PAGE_ID = "336d52d026fc8076ade8f7b2612f1fef"


def write_generated_queries(tmp_path, source_file: str):
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "source_file": source_file,
                        "query": "what did i write?",
                        "passage": "ignored",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_load_file_queries_maps_a_note_path_to_its_page_id(tmp_path):
    path = write_generated_queries(
        tmp_path,
        f"../data/notion-export-markdown/Journal/Take responsibility {PAGE_ID}.md",
    )

    [file_query] = load_file_queries(path)

    assert file_query.source == PAGE_ID
    assert file_query.has_page_id is True
    assert file_query.query == "what did i write?"


def test_a_note_without_a_page_id_can_never_be_hit(tmp_path):
    path = write_generated_queries(
        tmp_path, "../data/notion-export-markdown/Journal/career-direction.md"
    )

    [file_query] = load_file_queries(path)

    assert file_query.has_page_id is False
    assert file_query.source != PAGE_ID
