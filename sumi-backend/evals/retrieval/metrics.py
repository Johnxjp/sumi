"""Ranking metrics over per-rank gain lists. Pure functions, stdlib only."""

import math
from typing import Literal

GainScheme = Literal["exponential", "linear"]


def apply_gain(score: int, scheme: GainScheme = "exponential") -> int:
    """Map a relevance grade (0/1/2) to a gain.

    The exponential scheme maps to 0/1/3, so a highly-relevant chunk near the
    top outweighs several partially-relevant ones.
    """
    if scheme == "exponential":
        return 2**score - 1
    return score


def compute_dcg(gains: list[float], k: int) -> float:
    return sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains[:k]))


def compute_ndcg(gains: list[float], ideal_gains: list[float], k: int) -> float:
    """DCG@k of the ranking over the DCG@k of the best possible ranking.

    ideal_gains holds every judged positive for the query, whether or not it
    was retrieved, so a run is penalised for positives it missed entirely.
    """
    ideal = compute_dcg(sorted(ideal_gains, reverse=True), k)
    if ideal == 0:
        return 0.0
    return compute_dcg(gains, k) / ideal


def compute_recall(gains: list[float], num_relevant: int, k: int) -> float:
    if num_relevant == 0:
        return 0.0
    return sum(1 for gain in gains[:k] if gain > 0) / num_relevant


def compute_mrr(gains: list[float], k: int) -> float:
    for rank, gain in enumerate(gains[:k], start=1):
        if gain > 0:
            return 1 / rank
    return 0.0


def compute_precision(gains: list[float], k: int) -> float:
    if k == 0:
        return 0.0
    return sum(1 for gain in gains[:k] if gain > 0) / k
