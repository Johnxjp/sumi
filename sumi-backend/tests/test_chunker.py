from itertools import pairwise

import pytest

from src.retrieval.chunker import chunk_text


def sentence(label: str, length: int) -> str:
    return f"{label} " + "y" * (length - len(label) - 2) + "."


def test_short_document_is_one_chunk():
    text = "One sentence. Another sentence."
    chunks = chunk_text(text, max_chunk_size=100, min_chunk_size=10, chunk_overlap=20)
    assert chunks == [text]


def test_empty_and_whitespace_text():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_invalid_sizes_raise():
    with pytest.raises(ValueError):
        chunk_text("hello", max_chunk_size=10, min_chunk_size=10)


def test_splits_on_sentence_boundaries():
    s1, s2, s3 = (sentence(label, 80) for label in ("Alpha", "Bravo", "Charlie"))
    text = f"{s1} {s2} {s3}"
    chunks = chunk_text(text, max_chunk_size=100, min_chunk_size=50, chunk_overlap=0)
    assert chunks == [s1, s2, s3]


def test_merges_sentences_up_to_max_size():
    s1, s2, s3, s4 = (
        sentence(label, 40) for label in ("Alpha", "Bravo", "Chas", "Delta")
    )
    text = f"{s1} {s2} {s3} {s4}"
    chunks = chunk_text(text, max_chunk_size=90, min_chunk_size=20, chunk_overlap=0)
    assert chunks == [f"{s1} {s2}", f"{s3} {s4}"]


def test_overlap_repeats_trailing_sentence_of_previous_chunk():
    sentences = [f"Sentence number {i} has a bunch of filler words." for i in range(10)]
    text = " ".join(sentences)
    chunks = chunk_text(text, max_chunk_size=120, min_chunk_size=20, chunk_overlap=60)
    assert len(chunks) > 1
    assert all(len(chunk) <= 120 for chunk in chunks)
    for prev, nxt in pairwise(chunks):
        first_sentence = nxt.split(". ", 1)[0] + "."
        assert prev.endswith(first_sentence)


def test_small_trailing_chunk_folds_into_previous():
    s1, s2, s3 = (sentence(label, 80) for label in ("Alpha", "Bravo", "Charlie"))
    s4 = sentence("Delta", 30)
    text = f"{s1} {s2} {s3} {s4}"
    chunks = chunk_text(text, max_chunk_size=100, min_chunk_size=50, chunk_overlap=0)
    assert chunks == [s1, s2, f"{s3} {s4}"]


def test_fold_deduplicates_overlap():
    sentences = [f"Sentence number {i} has a bunch of filler words." for i in range(4)]
    tail = "The end."
    text = " ".join(sentences) + " " + tail
    chunks = chunk_text(text, max_chunk_size=120, min_chunk_size=60, chunk_overlap=60)
    joined = " ".join(chunks)
    assert joined.count(tail) == 1
    assert chunks[-1].endswith(tail)
    assert all(len(chunk) >= 60 for chunk in chunks)


def test_long_unbroken_text_is_hard_split_within_max():
    big = "B" * 300 + "."
    text = f"Short first sentence here. {big} Short last sentence here."
    chunks = chunk_text(text, max_chunk_size=100, min_chunk_size=10, chunk_overlap=0)
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert "".join(chunks).count("B") == 300


def test_paragraph_break_preserved_within_chunk():
    p1 = "Alpha alpha alpha alpha one. Alpha alpha alpha alpha two."
    p2 = "Bravo bravo bravo bravo one. Bravo bravo bravo bravo two."
    p3 = "Circa circa circa circa one. Circa circa circa circa two."
    text = f"{p1}\n\n{p2}\n\n{p3}"
    chunks = chunk_text(text, max_chunk_size=120, min_chunk_size=10, chunk_overlap=0)
    assert chunks == [f"{p1}\n\n{p2}", p3]
