"""Filesystem layout shared by the app, the annotation tool and the eval harness."""

from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
DATA_DIR = REPO_ROOT.parent / "data"
ANNOTATIONS_PATH = DATA_DIR / "annotations.json"
