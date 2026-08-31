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


def test_compute_dcg_discounts_by_log2_of_rank():
    assert compute_dcg([3, 0, 1], 10) == pytest.approx(3 + 0 + 1 / 2)


def test_compute_dcg_truncates_at_k():
    assert compute_dcg([3, 1], 1) == pytest.approx(3.0)


def test_compute_ndcg_penalises_positives_that_were_not_retrieved():
    # Retrieved [3, 0, 1] while the query has judged positives 3, 1 and 3.
    dcg = 3 + 1 / 2
    ideal = 3 + 3 / math.log2(3) + 1 / 2
    assert compute_ndcg([3, 0, 1], [3, 1, 3], 10) == pytest.approx(dcg / ideal)


def test_compute_ndcg_is_one_for_a_perfect_ranking():
    assert compute_ndcg([3, 1], [3, 1], 10) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("gains", "ideal", "expected"),
    [([], [3], 0.0), ([0, 0], [], 0.0), ([0, 0], [3], 0.0)],
)
def test_compute_ndcg_edge_cases(gains, ideal, expected):
    assert compute_ndcg(gains, ideal, 10) == expected


def test_compute_ndcg_at_5_ignores_later_ranks():
    gains = [0, 0, 0, 0, 0, 3]
    assert compute_ndcg(gains, [3], 5) == 0.0
    assert compute_ndcg(gains, [3], 10) > 0.0


def test_compute_recall_counts_all_judged_positives_as_denominator():
    assert compute_recall([3, 0, 1], num_relevant=4, k=10) == pytest.approx(0.5)


def test_compute_recall_without_positives_is_zero():
    assert compute_recall([0], num_relevant=0, k=10) == 0.0


@pytest.mark.parametrize(
    ("gains", "expected"), [([0, 0, 1], 1 / 3), ([3], 1.0), ([0, 0], 0.0)]
)
def test_compute_mrr(gains, expected):
    assert compute_mrr(gains, 10) == pytest.approx(expected)


def test_compute_mrr_ignores_hits_beyond_k():
    assert compute_mrr([0, 0, 3], 2) == 0.0


def test_compute_precision_divides_by_k():
    assert compute_precision([3, 0, 1], 10) == pytest.approx(0.2)


def test_compute_precision_at_zero_k():
    assert compute_precision([3], 0) == 0.0
