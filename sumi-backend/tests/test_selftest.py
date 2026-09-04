import json

import pytest

from evals.retrieval.qrels import load_graded_qrels
from evals.retrieval.selftest import find_page_ids, find_pooled_chunk_keys, split_misses

PAGE_A = "336d52d026fc8076ade8f7b2612f1fef"
PAGE_B = "146d52d026fc8065a351fc6e2ea53f8b"


@pytest.fixture
def annotations_path(tmp_path):
    path = tmp_path / "annotations.json"
    path.write_text(
        json.dumps(
            {
                "queries": {
                    "A Query": {
                        "query_text": "A Query",
                        "annotations": {
                            "k1": {
                                "score": 2,
                                "text": "still here",
                                "sources": [
                                    {
                                        "retriever": "qwen",
                                        "chunk_id": f"Journal/A {PAGE_A}.md#0",
                                        "rank": 3,
                                    },
                                    {
                                        "retriever": "bge-m3",
                                        "chunk_id": f"{PAGE_B}#0",
                                        "rank": 1,
                                    },
                                ],
                            },
                            "k2": {
                                "score": 0,
                                "text": "deep in the tail",
                                "sources": [
                                    {
                                        "retriever": "qwen",
                                        "chunk_id": f"{PAGE_B}#4",
                                        "rank": 44,
                                    }
                                ],
                            },
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_pooled_judgments_are_collected_by_chunk_key(annotations_path):
    assert find_pooled_chunk_keys(annotations_path, "qwen", 10) == {"a query": {"k1"}}


def test_judgments_below_the_pool_depth_are_not_collected(annotations_path):
    assert find_pooled_chunk_keys(annotations_path, "qwen", 50) == {
        "a query": {"k1", "k2"}
    }


def test_only_the_named_retrievers_judgments_are_collected(annotations_path):
    assert find_pooled_chunk_keys(annotations_path, "bge-m3", 10) == {"a query": {"k1"}}


def test_find_page_ids_reads_the_page_out_of_an_export_path(annotations_path):
    qrel = load_graded_qrels(annotations_path)["a query"]

    # get_chunk_id returns the alphabetically first recorded id for a judgment.
    assert find_page_ids(qrel, ["k1"]) == {"k1": PAGE_B}
    assert find_page_ids(qrel, ["k2"]) == {"k2": PAGE_B}


def test_find_page_ids_skips_a_judgment_with_no_usable_id(annotations_path):
    qrel = load_graded_qrels(annotations_path)["a query"]
    assert find_page_ids(qrel, ["never-judged"]) == {}


@pytest.mark.parametrize(
    ("keys_by_page", "expected"),
    [
        ({PAGE_A: {"k1"}}, (["k1"], [])),
        ({PAGE_A: {"other"}}, ([], ["k1"])),
        ({}, ([], ["k1"])),
    ],
    ids=[
        "text-still-there-so-the-join-broke",
        "text-gone-so-the-page-changed",
        "page-has-no-chunks-at-all",
    ],
)
def test_split_misses_tells_a_broken_join_from_an_edited_page(keys_by_page, expected):
    assert split_misses(["k1"], {"k1": PAGE_A}, keys_by_page) == expected


def test_a_judgment_whose_page_is_unknown_counts_as_a_failure():
    assert split_misses(["k1"], {}, {}) == (["k1"], [])
