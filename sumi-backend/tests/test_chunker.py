from itertools import pairwise

import pytest

from src.retrieval.chunker import chunk_text

LABELS = ["Alpha", "Bravo", "Charlie", "Delta"]


def sentence(label: str, length: int) -> str:
    return f"{label} " + "y" * (length - len(label) - 2) + "."


@pytest.mark.parametrize("text", ["", "   \n  "], ids=["empty", "whitespace"])
def test_empty_and_whitespace_text_yield_no_chunks(text):
    assert chunk_text(text) == []


@pytest.mark.parametrize(
    ("max_chunk_size", "min_chunk_size"),
    [(10, 10), (5, 10)],
    ids=["equal", "min-exceeds-max"],
)
def test_invalid_sizes_raise(max_chunk_size, min_chunk_size):
    with pytest.raises(ValueError):
        chunk_text(
            "hello", max_chunk_size=max_chunk_size, min_chunk_size=min_chunk_size
        )


@pytest.mark.parametrize(
    ("lengths", "max_chunk_size", "min_chunk_size", "expected_groups"),
    [
        pytest.param([15, 16], 100, 10, [[0, 1]], id="short-document-is-one-chunk"),
        pytest.param(
            [80, 80, 80], 100, 50, [[0], [1], [2]], id="splits-on-sentence-boundaries"
        ),
        pytest.param(
            [40, 40, 40, 40], 90, 20, [[0, 1], [2, 3]], id="merges-up-to-max-size"
        ),
        pytest.param(
            [80, 80, 80, 30],
            100,
            50,
            [[0], [1], [2, 3]],
            id="small-tail-folds-into-previous",
        ),
    ],
)
def test_sentences_group_into_expected_chunks(
    lengths, max_chunk_size, min_chunk_size, expected_groups
):
    sentences = [sentence(label, n) for label, n in zip(LABELS, lengths)]
    text = " ".join(sentences)
    chunks = chunk_text(
        text,
        max_chunk_size=max_chunk_size,
        min_chunk_size=min_chunk_size,
        chunk_overlap=0,
    )
    assert chunks == [
        " ".join(sentences[i] for i in group) for group in expected_groups
    ]


def test_overlap_repeats_trailing_sentence_of_previous_chunk():
    sentences = [f"Sentence number {i} has a bunch of filler words." for i in range(10)]
    text = " ".join(sentences)
    chunks = chunk_text(text, max_chunk_size=120, min_chunk_size=20, chunk_overlap=60)
    assert len(chunks) > 1
    assert all(len(chunk) <= 120 for chunk in chunks)
    for prev, nxt in pairwise(chunks):
        first_sentence = nxt.split(". ", 1)[0] + "."
        assert prev.endswith(first_sentence)


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
