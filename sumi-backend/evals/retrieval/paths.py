"""Filesystem layout of the eval harness. Plain Python, no env vars."""

from src.paths import ANNOTATIONS_PATH, DATA_DIR

GENERATED_QUERIES_PATH = DATA_DIR / "datasets" / "queries.json"
SPLIT_PATH = DATA_DIR / "datasets" / "split.json"
RUNS_DIR = DATA_DIR / "eval_runs"
UNJUDGED_QUEUE_PATH = DATA_DIR / "unjudged_queue.json"

__all__ = [
    "ANNOTATIONS_PATH",
    "GENERATED_QUERIES_PATH",
    "RUNS_DIR",
    "SPLIT_PATH",
    "UNJUDGED_QUEUE_PATH",
]
