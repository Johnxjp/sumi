import pytest

from evals.retrieval.diagnose import (
    compute_deltas,
    count_arm_contributions,
    diff_results,
    find_annotated,
    format_positions,
)


def make_record(
    query_key: str, value: float, kind: str = "annotated", metric: str = "ndcg@10"
) -> dict:
    return {
        "query": query_key,
        "query_key": query_key,
        "kind": kind,
        "split": "train",
        "metrics": {metric: value},
        "results": [],
        "positives": [],
    }


def test_find_annotated_drops_generated_records():
    records = [make_record("a", 0.5), make_record("b", 0.5, kind="generated")]
    assert [r["query_key"] for r in find_annotated(records)] == ["a"]


@pytest.mark.parametrize(
    ("positives", "expected"),
    [
        ([{"rank": 1}, {"rank": None}, {"rank": 4}, {"rank": None}], "1,4,miss(2)"),
        ([], "-"),
    ],
)
def test_format_positions(positives, expected):
    assert format_positions({"positives": positives}) == expected


def test_count_arm_contributions_counts_rows_per_arm():
    record = {
        "results": [
            {"arms": {"qwen": 1, "fts": 3}},
            {"arms": {"qwen": 2}},
            {"arms": {}},
        ]
    }
    assert count_arm_contributions(record) == {"qwen": 2, "fts": 1}


@pytest.mark.parametrize(
    ("before", "after", "metric", "expected"),
    [
        (
            [make_record("a", 0.9), make_record("b", 0.1)],
            [make_record("a", 0.4), make_record("b", 0.6)],
            "ndcg@10",
            [("a", -0.5), ("b", 0.5)],
        ),
        ([make_record("a", 0.5)], [make_record("b", 0.5)], "ndcg@10", []),
        (
            [make_record("a", 1.0, metric="file_mrr@10")],
            [make_record("a", 0.5, metric="file_mrr@10")],
            "file_mrr@10",
            [("a", -0.5)],
        ),
        (
            [make_record("a", 1.0, metric="file_mrr@10")],
            [make_record("a", 0.5, metric="file_mrr@10")],
            "ndcg@10",
            [],
        ),
    ],
    ids=[
        "regressions-first",
        "absent-from-earlier-run-skipped",
        "named-metric",
        "missing-metric-skipped",
    ],
)
def test_compute_deltas(before, after, metric, expected):
    deltas = compute_deltas(before, after, metric=metric)
    assert [d["query_key"] for d in deltas] == [key for key, _ in expected]
    assert [d["delta"] for d in deltas] == pytest.approx([d for _, d in expected])


def test_diff_results_reports_entries_exits_and_moves():
    before = [{"id": "a", "rank": 1}, {"id": "b", "rank": 2}]
    after = [{"id": "b", "rank": 1}, {"id": "c", "rank": 2}]
    diff = diff_results(before, after)
    assert [row["id"] for row in diff["gained"]] == ["c"]
    assert [row["id"] for row in diff["lost"]] == ["a"]
    assert diff["moved"] == [("b", 2, 1)]
