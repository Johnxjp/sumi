import math

import pytest

from evals.retrieval.metrics import (
    apply_gain,
    compute_dcg,
    compute_mrr,
    compute_ndcg,
    compute_precision,
    compute_recall,
)


@pytest.mark.parametrize(
    ("score", "scheme", "expected"),
    [
        (0, "exponential", 0),
        (1, "exponential", 1),
        (2, "exponential", 3),
        (2, "linear", 2),
    ],
)
def test_apply_gain(score, scheme, expected):
    assert apply_gain(score, scheme) == expected


@pytest.mark.parametrize(
    ("gains", "k", "expected"),
    [([3, 0, 1], 10, 3 + 0 + 1 / 2), ([3, 1], 1, 3.0)],
    ids=["discounts-by-log2-of-rank", "truncates-at-k"],
)
def test_compute_dcg(gains, k, expected):
    assert compute_dcg(gains, k) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("gains", "ideal", "k", "expected"),
    [
        # Retrieved [3, 0, 1] while the query has judged positives 3, 1 and 3.
        ([3, 0, 1], [3, 1, 3], 10, (3 + 1 / 2) / (3 + 3 / math.log2(3) + 1 / 2)),
        ([3, 1], [3, 1], 10, 1.0),
        ([], [3], 10, 0.0),
        ([0, 0], [], 10, 0.0),
        ([0, 0], [3], 10, 0.0),
        ([0, 0, 0, 0, 0, 3], [3], 5, 0.0),
        ([0, 0, 0, 0, 0, 3], [3], 10, 1 / math.log2(7)),
    ],
    ids=[
        "penalises-positives-not-retrieved",
        "perfect-ranking",
        "empty-ranking",
        "no-positives",
        "all-misses",
        "hit-beyond-k-ignored",
        "hit-within-k-counted",
    ],
)
def test_compute_ndcg(gains, ideal, k, expected):
    assert compute_ndcg(gains, ideal, k) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("gains", "num_relevant", "expected"),
    [([3, 0, 1], 4, 0.5), ([0], 0, 0.0)],
    ids=["all-judged-positives-as-denominator", "no-positives"],
)
def test_compute_recall(gains, num_relevant, expected):
    assert compute_recall(gains, num_relevant, k=10) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("gains", "k", "expected"),
    [([0, 0, 1], 10, 1 / 3), ([3], 10, 1.0), ([0, 0], 10, 0.0), ([0, 0, 3], 2, 0.0)],
    ids=["first-hit-at-3", "first-hit-at-1", "no-hit", "hit-beyond-k-ignored"],
)
def test_compute_mrr(gains, k, expected):
    assert compute_mrr(gains, k) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("gains", "k", "expected"),
    [([3, 0, 1], 10, 0.2), ([3], 0, 0.0)],
    ids=["divides-by-k", "k-of-zero"],
)
def test_compute_precision(gains, k, expected):
    assert compute_precision(gains, k) == pytest.approx(expected)
