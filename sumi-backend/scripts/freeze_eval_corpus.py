"""Freeze the synced notes as a dated eval corpus of whole documents.

    uv run python -m scripts.freeze_eval_corpus

An eval corpus is the fixed set of notes that retrieval experiments search, so
that when a number moves it is the method that changed and not the material.
The notes synced from Notion cannot serve as one directly: every sync rewrites
the pages that changed, so labels made against them would decay. Copying them
once, under a date, gives something that holds still.

This writes whole documents, one markdown file per Notion page, not chunks:

    data/eval-corpus-2026-09-05/
        metadata.json
        corpus/...            one .md per page, in the mirror's folder layout

Chunking and embedding are then pipeline choices applied *to* this corpus
rather than properties baked into it, so a new chunker can be measured on the
same notes. The cost is that a snapshot is not searchable on its own: building
chunk tables from it is a step of its own.
"""

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql

from src.config import app_config
from src.notion.client import NOTION_VERSION
from src.notion.mirror import regenerate_mirror
from src.paths import DATA_DIR

CORPUS_DIR_NAME = "corpus"
METADATA_NAME = "metadata.json"


def load_documents(database_url: str) -> list[tuple[str, str]]:
    """Every synced page as (path inside the corpus, markdown)."""
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            sql.SQL(
                "SELECT mirror_path, markdown FROM notion_objects WHERE kind = 'page' "
                "AND markdown IS NOT NULL AND mirror_path <> '' ORDER BY mirror_path"
            )
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


def load_latest_sync_run(database_url: str) -> dict[str, object] | None:
    """The run that produced this corpus, for the record."""
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            "SELECT started_at, finished_at, mode, status, pages_indexed, requests "
            "FROM notion_sync_runs WHERE status = 'ok' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return {
        "started_at": row[0].isoformat(),
        "finished_at": row[1].isoformat() if row[1] else None,
        "mode": row[2],
        "status": row[3],
        "pages_indexed": row[4],
        "requests": row[5],
    }


def get_renderer_commit() -> str:
    """The commit whose normalising rules produced this text.

    The same Notion page renders differently as those rules change, so a
    corpus is only reproducible alongside the code that wrote it.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def measure(corpus_dir: Path) -> tuple[int, int]:
    files = list(corpus_dir.rglob("*.md"))
    return len(files), sum(path.stat().st_size for path in files)


def build_metadata(
    name: str, documents: int, size_bytes: int, sync_run: dict[str, object] | None
) -> dict[str, object]:
    return {
        "name": name,
        "created_at": datetime.now(UTC).isoformat(),
        "source": "notion api",
        "notion_api_version": NOTION_VERSION,
        "unit": "document",
        "documents": documents,
        "bytes": size_bytes,
        "renderer_commit": get_renderer_commit(),
        "sync_run": sync_run,
        "description": (
            "Whole Notion pages, one markdown file per page, frozen so that "
            "retrieval experiments and relevance labels have material that does "
            "not move. Chunking and embedding are applied to this corpus, not "
            "baked into it."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name",
        default=f"eval-corpus-{datetime.now(UTC).date().isoformat()}",
        help="folder name, dated by default",
    )
    parser.add_argument("--out-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    target = args.out_dir / args.name
    if target.exists():
        raise SystemExit(
            f"{target} already exists. A frozen corpus is never rewritten: "
            "pick another --name."
        )

    documents = load_documents(app_config.database_url)
    if not documents:
        raise SystemExit("no synced pages found; run scripts.sync first.")

    corpus_dir = target / CORPUS_DIR_NAME
    corpus_dir.parent.mkdir(parents=True, exist_ok=True)
    written = regenerate_mirror(documents, corpus_dir)
    count, size_bytes = measure(corpus_dir)

    metadata = build_metadata(
        args.name, count, size_bytes, load_latest_sync_run(app_config.database_url)
    )
    (target / METADATA_NAME).write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )

    print(f"froze {written} documents ({size_bytes / 1_000_000:.1f} MB) into {target}")
    print(
        f"  {METADATA_NAME} written; renderer commit {metadata['renderer_commit'][:7]}"
    )


if __name__ == "__main__":
    main()
