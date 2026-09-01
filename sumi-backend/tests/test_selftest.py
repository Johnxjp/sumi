import json

from evals.retrieval.selftest import find_pooled_chunk_ids


def test_find_pooled_chunk_ids_collects_only_the_named_retriever(tmp_path):
    path = tmp_path / "annotations.json"
    path.write_text(
        json.dumps(
            {
                "queries": {
                    "A Query": {
                        "annotations": {
                            "k1": {
                                "score": 2,
                                "sources": [
                                    {"retriever": "qwen", "chunk_id": "a#0", "rank": 3},
                                    {
                                        "retriever": "bge-m3",
                                        "chunk_id": "b#0",
                                        "rank": 1,
                                    },
                                ],
                            },
                            "k2": {
                                "score": 0,
                                "sources": [
                                    {"retriever": "qwen", "chunk_id": "c#0", "rank": 44}
                                ],
                            },
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert find_pooled_chunk_ids(path, "qwen", 10) == {"a query": {"a#0"}}
