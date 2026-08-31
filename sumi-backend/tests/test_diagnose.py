import json

from evals.retrieval.diagnose import (
    compute_deltas,
    count_arm_contributions,
    diff_results,
    find_annotated,
    format_positions,
)
from evals.retrieval.selftest import find_pooled_chunk_ids


def make_record(query_key: str, ndcg: float, kind: str = "annotated") -> dict:
    return {
        "query": query_key,
        "query_key": query_key,
        "kind": kind,
        "split": "train",
        "metrics": {"ndcg@10": ndcg},
        "results": [],
        "positives": [],
    }


def test_find_annotated_drops_generated_records():
    records = [make_record("a", 0.5), make_record("b", 0.5, kind="generated")]
    assert [r["query_key"] for r in find_annotated(records)] == ["a"]


def test_format_positions_lists_ranks_and_counts_misses():
    record = {"positives": [{"rank": 1}, {"rank": None}, {"rank": 4}, {"rank": None}]}
    assert format_positions(record) == "1,4,miss(2)"


def test_format_positions_without_positives():
    assert format_positions({"positives": []}) == "-"


def test_count_arm_contributions_counts_rows_per_arm():
    record = {
        "results": [
            {"arms": {"qwen": 1, "fts": 3}},
            {"arms": {"qwen": 2}},
            {"arms": {}},
        ]
    }
    assert count_arm_contributions(record) == {"qwen": 2, "fts": 1}


def test_compute_deltas_sorts_regressions_first():
    before = [make_record("a", 0.9), make_record("b", 0.1)]
    after = [make_record("a", 0.4), make_record("b", 0.6)]
    deltas = compute_deltas(before, after)
    assert [d["query_key"] for d in deltas] == ["a", "b"]
    assert deltas[0]["delta"] == -0.5


def test_compute_deltas_skips_queries_absent_from_the_earlier_run():
    deltas = compute_deltas([make_record("a", 0.5)], [make_record("b", 0.5)])
    assert deltas == []


def test_compute_deltas_skips_records_without_the_metric():
    before = [{**make_record("a", 0.5), "metrics": {"file_mrr@10": 1.0}}]
    after = [{**make_record("a", 0.5), "metrics": {"file_mrr@10": 0.5}}]
    assert compute_deltas(before, after, metric="file_mrr@10")[0]["delta"] == -0.5
    assert compute_deltas(before, after) == []


def test_diff_results_reports_entries_exits_and_moves():
    before = [{"id": "a", "rank": 1}, {"id": "b", "rank": 2}]
    after = [{"id": "b", "rank": 1}, {"id": "c", "rank": 2}]
    diff = diff_results(before, after)
    assert [row["id"] for row in diff["gained"]] == ["c"]
    assert [row["id"] for row in diff["lost"]] == ["a"]
    assert diff["moved"] == [("b", 2, 1)]


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
