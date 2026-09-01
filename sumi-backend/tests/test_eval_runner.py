import json
import math

import pytest

from evals.retrieval.qrels import FileQuery, GradedQuery
from evals.retrieval.runner import (
    ExperimentConfig,
    QueryRecord,
    aggregate,
    build_result_rows,
    find_positive_ranks,
    persist_run,
    score_annotated,
    score_generated,
    split_of,
)
from evals.retrieval.split import Split
from src.retrieval.search_config import QWEN_ARM, RetrievalConfig


@pytest.fixture
def qrel():
    return GradedQuery(
        query_text="a query",
        gain_by_chunk_key={"hit": 3, "partial": 1, "missed": 3, "negative": 0},
        chunk_key_by_chunk_id={
            "a#0": "hit",
            "b#0": "partial",
            "c#0": "missed",
            "d#0": "negative",
        },
    )


def make_rows(*ids: str) -> list[dict]:
    return [
        {"id": i, "text": f"text {i}", "source": f"{i}.md", "metadata": {"title": i}}
        for i in ids
    ]


def test_score_annotated_counts_unjudged_rows_as_irrelevant(qrel):
    # Retrieved gains [3, unjudged, 1]; the ideal ranking also holds the missed 3.
    metrics = score_annotated(qrel, make_rows("a#0", "unseen#0", "b#0"))
    ideal = 3 + 3 / math.log2(3) + 1 / 2
    assert metrics == pytest.approx(
        {
            "ndcg@10": (3 + 1 / 2) / ideal,
            "ndcg@10_condensed": (3 + 1 / math.log2(3)) / ideal,
            "ndcg@5": (3 + 1 / 2) / ideal,
            "recall@10": 2 / 3,
            "mrr@10": 1.0,
            "precision@10": 0.2,
            "judged_coverage@10": 2 / 3,
        }
    )


def test_find_positive_ranks_reports_where_each_positive_landed(qrel):
    positives = find_positive_ranks(qrel, make_rows("b#0", "unseen#0", "a#0"))
    assert positives == [
        {"chunk_key": "hit", "chunk_id": "a#0", "gain": 3, "rank": 3},
        {"chunk_key": "missed", "chunk_id": "c#0", "gain": 3, "rank": None},
        {"chunk_key": "partial", "chunk_id": "b#0", "gain": 1, "rank": 1},
    ]


def test_build_result_rows_tags_each_row_with_its_judgment(qrel):
    [judged, unjudged] = build_result_rows(make_rows("a#0", "unseen#0"), qrel)
    assert (judged["rank"], judged["gain"], judged["judged"]) == (1, 3, True)
    assert (unjudged["rank"], unjudged["gain"], unjudged["judged"]) == (2, None, False)
    assert judged["title"] == "a#0"

    [unscored] = build_result_rows(make_rows("a#0"), None)
    assert (unscored["gain"], unscored["judged"]) == (None, False)


def test_score_generated_matches_on_the_source_file():
    file_query = FileQuery(query="q", source="b#0.md")
    assert score_generated(file_query, make_rows("a#0", "b#0")) == {
        "file_recall@10": 1.0,
        "file_mrr@10": 0.5,
    }
    assert score_generated(file_query, make_rows("a#0")) == {
        "file_recall@10": 0.0,
        "file_mrr@10": 0.0,
    }


def make_record(kind: str, split: str, **metrics) -> QueryRecord:
    return QueryRecord(
        query="q",
        query_key="q",
        kind=kind,
        split=split,
        metrics=metrics,
        results=[],
    )


ANNOTATED_METRICS = {
    "ndcg@10": 0.5,
    "ndcg@10_condensed": 0.5,
    "ndcg@5": 0.5,
    "recall@10": 0.5,
    "mrr@10": 0.5,
    "precision@10": 0.5,
    "judged_coverage@10": 0.5,
}


def test_aggregate_averages_one_split_with_annotated_and_generated_apart():
    records = [
        make_record("annotated", "train", **ANNOTATED_METRICS, num_relevant=2),
        make_record(
            "annotated",
            "train",
            **{**ANNOTATED_METRICS, "ndcg@10": 0.0},
            num_relevant=0,
        ),
        make_record(
            "annotated", "val", **{**ANNOTATED_METRICS, "ndcg@10": 1.0}, num_relevant=2
        ),
        make_record(
            "generated", "train", **{"file_recall@10": 1.0, "file_mrr@10": 0.5}
        ),
        make_record(
            "generated", "train", **{"file_recall@10": 0.0, "file_mrr@10": 0.0}
        ),
        make_record("generated", "val", **{"file_recall@10": 0.0, "file_mrr@10": 0.0}),
    ]
    assert aggregate(records, "train") == {
        "annotated": {
            **ANNOTATED_METRICS,
            "num_queries": 1,
            "excluded_zero_positive": 1,
        },
        "generated": {"file_recall@10": 0.5, "file_mrr@10": 0.25, "num_queries": 2},
    }
    assert aggregate(records, "val")["annotated"]["ndcg@10"] == 1.0


def test_split_of_labels_unassigned_queries():
    split = Split(seed=1, train={"a"}, val={"b"})
    assert split_of(split, "a") == "train"
    assert split_of(split, "b") == "val"
    assert split_of(split, "c") == "unassigned"


def test_persist_run_writes_the_three_run_files(tmp_path):
    config = ExperimentConfig(
        name="demo", retrieval=RetrievalConfig(arms=(QWEN_ARM,)), notes="why"
    )
    records = [make_record("annotated", "train", **ANNOTATED_METRICS, num_relevant=1)]
    run_dir = tmp_path / "runs" / "demo"

    persist_run(run_dir, config, {"run_id": "demo"}, records)

    stored_config = json.loads((run_dir / "config.json").read_text())
    assert stored_config["retrieval"]["arms"][0]["table"] == "chunks_qwen"
    assert stored_config["notes"] == "why"
    assert json.loads((run_dir / "metrics.json").read_text()) == {"run_id": "demo"}
    assert (
        json.loads((run_dir / "per_query.json").read_text())[0]["kind"] == "annotated"
    )
