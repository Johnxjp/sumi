import json

import pytest

from evals.retrieval.compare import format_metric, load_runs


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ({"ndcg@10": 0.5, "num_queries": 3}, "  0.500"),
        ({"num_queries": 3}, "      -"),
        ({"ndcg@10": 0.0, "num_queries": 0}, "      -"),
    ],
)
def test_format_metric_marks_absent_values(block, expected):
    assert format_metric(block, "ndcg@10", 7) == expected


def test_load_runs_reads_every_run_directory(tmp_path):
    for name in ("b-run", "a-run"):
        run_dir = tmp_path / name
        run_dir.mkdir()
        (run_dir / "metrics.json").write_text(json.dumps({"run_id": name}))
    (tmp_path / "not-a-run").mkdir()

    assert [run["run_id"] for run in load_runs(tmp_path)] == ["a-run", "b-run"]
