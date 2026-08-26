import json

from src.annotation.models import AnnotateRequest, RetrieverSource
from src.annotation.store import AnnotationStore


def make_request(**overrides) -> AnnotateRequest:
    defaults = {
        "query": "How do I configure ingress",
        "chunk_key": "abc123",
        "score": 2,
        "text": "chunk text",
        "metadata": {"note": "k8s.md"},
        "sources": [
            RetrieverSource(retriever="r1", chunk_id="uuid-1", rank=1, score=0.8)
        ],
    }
    defaults.update(overrides)
    return AnnotateRequest(**defaults)


def test_upsert_then_get_roundtrip(tmp_path):
    store = AnnotationStore(tmp_path / "annotations.json")
    store.upsert(make_request())
    assert store.get_for_query("How do I configure ingress") == {"abc123": 2}


def test_query_lookup_whitespace_and_case_insensitive(tmp_path):
    store = AnnotationStore(tmp_path / "annotations.json")
    store.upsert(make_request())
    assert store.get_for_query("  how do I  CONFIGURE ingress ") == {"abc123": 2}


def test_get_unknown_query_returns_empty(tmp_path):
    store = AnnotationStore(tmp_path / "annotations.json")
    assert store.get_for_query("never seen") == {}


def test_overwrite_updates_score_and_sources_preserves_created_at(tmp_path):
    store = AnnotationStore(tmp_path / "annotations.json")
    store.upsert(make_request(score=0))

    data = json.loads((tmp_path / "annotations.json").read_text())
    entry = data["queries"]["how do i configure ingress"]["annotations"]["abc123"]
    original_created_at = entry["created_at"]

    new_sources = [
        RetrieverSource(retriever="r2", chunk_id="uuid-9", rank=3, score=0.5)
    ]
    store.upsert(make_request(score=1, sources=new_sources))

    data = json.loads((tmp_path / "annotations.json").read_text())
    entry = data["queries"]["how do i configure ingress"]["annotations"]["abc123"]
    assert entry["score"] == 1
    assert entry["created_at"] == original_created_at
    assert entry["updated_at"] >= original_created_at
    assert len(entry["sources"]) == 1
    assert entry["sources"][0]["retriever"] == "r2"
    assert len(data["queries"]["how do i configure ingress"]["annotations"]) == 1


def test_persists_across_store_instances(tmp_path):
    path = tmp_path / "annotations.json"
    AnnotationStore(path).upsert(make_request())
    assert AnnotationStore(path).get_for_query("How do I configure ingress") == {
        "abc123": 2
    }


def test_file_is_valid_json_with_expected_shape(tmp_path):
    path = tmp_path / "annotations.json"
    store = AnnotationStore(path)
    store.upsert(make_request())
    store.upsert(make_request(query="another query", chunk_key="def456", score=0))

    data = json.loads(path.read_text())
    assert data["version"] == 1
    assert set(data["queries"]) == {"how do i configure ingress", "another query"}
    entry = data["queries"]["how do i configure ingress"]
    assert entry["query_text"] == "How do I configure ingress"
    annotation = entry["annotations"]["abc123"]
    assert annotation["text"] == "chunk text"
    assert annotation["metadata"] == {"note": "k8s.md"}
    assert annotation["sources"][0] == {
        "retriever": "r1",
        "chunk_id": "uuid-1",
        "rank": 1,
        "score": 0.8,
    }
