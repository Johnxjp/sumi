from src.annotation.pooling import compute_chunk_key, parse_result, pool_results


def test_same_text_different_whitespace_same_key():
    key_a = compute_chunk_key("hello  world\n", "r1", "id1")
    key_b = compute_chunk_key("hello world", "r2", "id2")
    assert key_a == key_b


def test_different_text_different_key():
    assert compute_chunk_key("hello", "r1", "id1") != compute_chunk_key(
        "goodbye", "r1", "id1"
    )


def test_missing_text_fallback_key_scoped_per_retriever():
    key_a = compute_chunk_key(None, "r1", "id1")
    key_b = compute_chunk_key(None, "r2", "id1")
    assert key_a == "noid:r1:id1"
    assert key_a != key_b


def test_parse_result_alternate_field_names():
    result = parse_result(
        {"doc_id": "d1", "content": "some text", "similarity": 0.5}, "r1"
    )
    assert result.chunk_id == "d1"
    assert result.text == "some text"
    assert result.score == 0.5

    result = parse_result(
        {"chunk_id": "c1", "chunk": "other", "score": 1, "doc_metadata": {"a": 1}},
        "r1",
    )
    assert result.chunk_id == "c1"
    assert result.text == "other"
    assert result.score == 1.0
    assert result.metadata == {"a": 1}


def test_parse_result_folds_source_into_metadata():
    result = parse_result(
        {
            "id": "n.md#0",
            "text": "t",
            "source": "Journal/n.md",
            "metadata": {"title": "n"},
        },
        "r1",
    )
    assert result.metadata == {"title": "n", "source": "Journal/n.md"}

    result = parse_result(
        {"id": "x", "text": "t", "source": "a.md", "metadata": {"source": "keep-me"}},
        "r1",
    )
    assert result.metadata["source"] == "keep-me"


def test_parse_result_unknown_dict_does_not_raise():
    result = parse_result({"weird_field": [1, 2, 3]}, "r1")
    assert result.text is None
    assert result.chunk_id is None
    assert result.score is None
    assert result.metadata == {}
    assert result.chunk_key == "noid:r1:None"


def test_pool_merges_same_text_across_retrievers():
    per_retriever = {
        "r1": [{"id": "a", "text": "shared chunk", "score": 0.9}],
        "r2": [
            {"id": "b", "text": "unique chunk", "score": 0.8},
            {"id": "c", "text": "shared chunk", "score": 0.7},
        ],
    }
    chunks = pool_results(per_retriever, {})
    assert len(chunks) == 2
    shared = next(c for c in chunks if c.text == "shared chunk")
    assert len(shared.sources) == 2
    ranks = {s.retriever: s.rank for s in shared.sources}
    assert ranks == {"r1": 1, "r2": 2}
    scores = {s.retriever: s.score for s in shared.sources}
    assert scores == {"r1": 0.9, "r2": 0.7}


def test_pool_prefills_existing_annotations():
    per_retriever = {
        "r1": [{"id": "a", "text": "annotated"}, {"id": "b", "text": "new"}]
    }
    annotated_key = compute_chunk_key("annotated", "r1", "a")
    chunks = pool_results(per_retriever, {annotated_key: 2})
    by_text = {c.text: c for c in chunks}
    assert by_text["annotated"].annotation == 2
    assert by_text["new"].annotation is None


def test_pool_ordering_deterministic():
    per_retriever = {
        "r1": [{"id": "a", "text": "first"}, {"id": "b", "text": "second"}],
        "r2": [{"id": "c", "text": "second"}, {"id": "d", "text": "third"}],
    }
    chunks_a = pool_results(per_retriever, {})
    chunks_b = pool_results(dict(reversed(per_retriever.items())), {})
    assert [c.chunk_key for c in chunks_a] == [c.chunk_key for c in chunks_b]
    assert chunks_a[0].text in ("first", "second")
    assert chunks_a[-1].text == "third"
