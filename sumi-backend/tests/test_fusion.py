import pytest

from src.retrieval.fusion import fuse_rrf


def make_row(row_id: str, score: float = 0.5) -> dict:
    return {
        "id": row_id,
        "text": f"text {row_id}",
        "source": f"{row_id}.md",
        "metadata": {},
        "score": score,
    }


@pytest.mark.parametrize(
    ("k", "expected_scores"),
    [(60, [1 / 61 + 1 / 62, 1 / 61]), (1, [1 / 2 + 1 / 3, 1 / 2])],
)
def test_fuse_rrf_sums_reciprocal_ranks_and_records_each_arm_rank(k, expected_scores):
    fused = fuse_rrf({"a": [make_row("x")], "b": [make_row("y"), make_row("x")]}, k=k)
    assert [row["id"] for row in fused] == ["x", "y"]
    assert [row["score"] for row in fused] == pytest.approx(expected_scores)
    assert [row["arms"] for row in fused] == [{"a": 1, "b": 2}, {"b": 1}]


def test_fuse_rrf_keeps_the_first_seen_text_and_source():
    duplicate = {**make_row("x"), "text": "second copy", "source": "other.md"}
    [fused] = fuse_rrf({"a": [make_row("x")], "b": [duplicate]})
    assert fused["text"] == "text x"
    assert fused["source"] == "x.md"


def test_fuse_rrf_applies_per_arm_weights():
    fused = fuse_rrf(
        {"a": [make_row("x")], "b": [make_row("y")]}, weights={"a": 2.0, "b": 0.5}
    )
    assert [row["id"] for row in fused] == ["x", "y"]
    assert fused[0]["score"] == pytest.approx(2.0 / 61)


def test_fuse_rrf_breaks_ties_by_id():
    fused = fuse_rrf({"a": [make_row("b")], "b": [make_row("a")]})
    assert [row["id"] for row in fused] == ["a", "b"]


@pytest.mark.parametrize(
    ("ranked", "expected"), [({}, []), ({"a": []}, []), ({"a": [make_row("x")]}, ["x"])]
)
def test_fuse_rrf_edge_cases(ranked, expected):
    assert [row["id"] for row in fuse_rrf(ranked)] == expected
