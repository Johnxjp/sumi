import json

import pytest

from evals.retrieval.qrels import GradedQuery
from evals.retrieval.queue import UnjudgedCandidate, append_unjudged
from src.annotation.pooling import compute_chunk_key


def make_candidate(
    chunk_id: str, rank: int, text: str = "some chunk"
) -> UnjudgedCandidate:
    return UnjudgedCandidate(
        query_key="a query",
        query_text="A Query",
        rank=rank,
        row={
            "id": chunk_id,
            "text": text,
            "source": "notes/a.md",
            "metadata": {"title": "A"},
        },
    )


@pytest.fixture
def qrels():
    return {
        "a query": GradedQuery(
            query_text="A Query",
            gain_by_chunk_key={"judgedkey": 3},
            chunk_key_by_chunk_id={"notes/judged.md#0": "judgedkey"},
        )
    }


def test_append_unjudged_writes_the_full_entry(tmp_path, qrels):
    path = tmp_path / "queue.json"
    added = append_unjudged(path, qrels, "run-1", [make_candidate("notes/a.md#0", 4)])
    assert added == 1
    [item] = json.loads(path.read_text()).values()
    assert item == {
        "query_key": "a query",
        "query": "A Query",
        "chunk_id": "notes/a.md#0",
        "chunk_key": compute_chunk_key("some chunk", "eval", "notes/a.md#0"),
        "text": "some chunk",
        "source": "notes/a.md",
        "title": "A",
        "best_rank": 4,
        "runs": ["run-1"],
        "first_seen_at": item["first_seen_at"],
    }


def test_append_unjudged_skips_judged_candidates(tmp_path, qrels):
    path = tmp_path / "queue.json"
    added = append_unjudged(
        path, qrels, "run-1", [make_candidate("notes/judged.md#0", 1)]
    )
    assert added == 0
    assert json.loads(path.read_text()) == {}


def test_append_unjudged_deduplicates_across_runs(tmp_path, qrels):
    path = tmp_path / "queue.json"
    append_unjudged(path, qrels, "run-1", [make_candidate("notes/a.md#0", 7)])
    added = append_unjudged(path, qrels, "run-2", [make_candidate("notes/a.md#0", 3)])
    assert added == 0
    [item] = json.loads(path.read_text()).values()
    assert item["best_rank"] == 3
    assert item["runs"] == ["run-1", "run-2"]


def test_append_unjudged_keeps_the_best_rank_seen(tmp_path, qrels):
    path = tmp_path / "queue.json"
    append_unjudged(path, qrels, "run-1", [make_candidate("notes/a.md#0", 2)])
    append_unjudged(path, qrels, "run-2", [make_candidate("notes/a.md#0", 9)])
    [item] = json.loads(path.read_text()).values()
    assert item["best_rank"] == 2
    assert item["runs"] == ["run-1", "run-2"]


def test_append_unjudged_drops_entries_that_have_since_been_judged(tmp_path, qrels):
    path = tmp_path / "queue.json"
    append_unjudged(path, qrels, "run-1", [make_candidate("notes/b.md#0", 1)])
    labelled = {
        "a query": GradedQuery(
            query_text="A Query",
            gain_by_chunk_key={"judgedkey": 1},
            chunk_key_by_chunk_id={"notes/b.md#0": "judgedkey"},
        )
    }
    append_unjudged(path, labelled, "run-2", [])
    assert json.loads(path.read_text()) == {}


def test_append_unjudged_counts_only_new_items(tmp_path, qrels):
    path = tmp_path / "queue.json"
    added = append_unjudged(
        path,
        qrels,
        "run-1",
        [
            make_candidate("notes/a.md#0", 1),
            make_candidate("notes/b.md#0", 2, text="other"),
        ],
    )
    assert added == 2
    assert len(json.loads(path.read_text())) == 2
