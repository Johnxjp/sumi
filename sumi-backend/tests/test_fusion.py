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


def test_fuse_rrf_sums_reciprocal_ranks():
    fused = fuse_rrf({"a": [make_row("x")], "b": [make_row("y"), make_row("x")]})
    by_id = {row["id"]: row for row in fused}
    assert by_id["x"]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert by_id["y"]["score"] == pytest.approx(1 / 61)
    assert [row["id"] for row in fused] == ["x", "y"]


def test_fuse_rrf_records_the_rank_each_arm_gave():
    fused = fuse_rrf({"a": [make_row("x")], "b": [make_row("y"), make_row("x")]})
    assert fused[0]["arms"] == {"a": 1, "b": 2}
    assert fused[1]["arms"] == {"b": 1}


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


def test_fuse_rrf_uses_k_to_flatten_rank_differences():
    fused = fuse_rrf({"a": [make_row("x"), make_row("y")]}, k=1)
    assert fused[0]["score"] == pytest.approx(1 / 2)
    assert fused[1]["score"] == pytest.approx(1 / 3)


def test_fuse_rrf_breaks_ties_by_id():
    fused = fuse_rrf({"a": [make_row("b")], "b": [make_row("a")]})
    assert [row["id"] for row in fused] == ["a", "b"]


@pytest.mark.parametrize(
    ("ranked", "expected"), [({}, []), ({"a": []}, []), ({"a": [make_row("x")]}, ["x"])]
)
def test_fuse_rrf_edge_cases(ranked, expected):
    assert [row["id"] for row in fuse_rrf(ranked)] == expected
