import json
from unittest import mock

from src.usage import (
    append_record,
    build_search_record,
    current_user_query,
    record_search,
)

CHUNKS = [
    {"rank": 1, "chunk_id": "336d52d026fc8076ade8f7b2612f1fef#0", "text": "a"},
    {"rank": 2, "chunk_id": "146d52d026fc8065a351fc6e2ea53f8b#2", "text": "b"},
]


def test_a_record_keeps_both_queries_and_the_ranked_chunk_ids():
    record = build_search_record(
        agent_query="personal vision",
        chunks=CHUNKS,
        retriever_version="rrf-3arm-k5",
        corpus_version="2026-09-01",
        user_query="What did I write in my personal vision?",
    )

    assert record["user_query"] == "What did I write in my personal vision?"
    assert record["agent_query"] == "personal vision"
    assert record["corpus_version"] == "2026-09-01"
    assert record["retriever_version"] == "rrf-3arm-k5"
    assert record["results"] == [
        {"chunk_id": "336d52d026fc8076ade8f7b2612f1fef#0", "rank": 1},
        {"chunk_id": "146d52d026fc8065a351fc6e2ea53f8b#2", "rank": 2},
    ]
    assert record["query_id"].startswith("q_")


def test_two_records_get_different_ids():
    first = build_search_record("q", [], "r", "2026-09-01")
    second = build_search_record("q", [], "r", "2026-09-01")

    assert first["query_id"] != second["query_id"]


def test_append_writes_one_line_of_json_per_record(tmp_path):
    path = tmp_path / "usage" / "searches.jsonl"

    append_record({"query_id": "q_1"}, path)
    append_record({"query_id": "q_2"}, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["query_id"] for line in lines] == ["q_1", "q_2"]


@mock.patch("src.usage.get_corpus_version", autospec=True, return_value="2026-09-01")
def test_the_users_own_wording_is_taken_from_the_turn(_version, tmp_path):
    path = tmp_path / "searches.jsonl"
    token = current_user_query.set("what did napoleon say about leadership?")
    try:
        record_search("napoleon leadership", CHUNKS, "rrf-3arm-k5", path)
    finally:
        current_user_query.reset(token)

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["user_query"] == "what did napoleon say about leadership?"
    assert record["agent_query"] == "napoleon leadership"


@mock.patch("src.usage.get_corpus_version", autospec=True, return_value="2026-09-01")
def test_a_search_outside_a_turn_has_no_user_query(_version, tmp_path):
    path = tmp_path / "searches.jsonl"

    record_search("napoleon leadership", CHUNKS, "rrf-3arm-k5", path)

    assert json.loads(path.read_text(encoding="utf-8"))["user_query"] is None


@mock.patch("src.usage.append_record", autospec=True, side_effect=OSError("disk full"))
@mock.patch("src.usage.get_corpus_version", autospec=True, return_value="2026-09-01")
def test_a_logging_failure_does_not_fail_the_search(_version, _append):
    record_search("napoleon leadership", CHUNKS, "rrf-3arm-k5")
