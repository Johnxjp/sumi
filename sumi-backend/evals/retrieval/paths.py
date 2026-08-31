"""Filesystem layout of the eval harness. Plain Python, no env vars."""

from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
DATA_DIR = REPO_ROOT.parent / "data"

ANNOTATIONS_PATH = DATA_DIR / "annotations.json"
GENERATED_QUERIES_PATH = DATA_DIR / "datasets" / "queries.json"
SPLIT_PATH = DATA_DIR / "datasets" / "split.json"
RUNS_DIR = DATA_DIR / "eval_runs"
UNJUDGED_QUEUE_PATH = DATA_DIR / "unjudged_queue.json"
