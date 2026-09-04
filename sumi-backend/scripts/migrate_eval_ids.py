"""Rewrite the human judgments from export paths to Notion page ids. Run once.

A judgment is a score a person gave to one chunk of a note. Each one records
the chunk's id, which used to be "{export file path}#{position in the note}"
and is now "{Notion page id}#{position}". The page id is already in the export
file name, so the note a judgment belongs to is known without a lookup; what
has to be found is which chunk of that note now holds the judged text, because
an edit near the top of a page shifts every later chunk boundary.

Judgments are joined to search results by a hash of the text, so this rewrite
is a convenience, not a correctness fix: it keeps the fast path working and
keeps the file readable. A judgment whose text no longer appears anywhere in
its page is left exactly as it was and reported as **orphaned** — the note was
edited in Notion since it was labelled, or the sync renders it differently.
It still counts as a positive in the ideal ordering, so recall on that query
becomes a floor rather than an estimate.

    uv run python -m scripts.migrate_eval_ids [--dry-run]

The original file is copied to annotations.json.before-page-ids first.
"""

import argparse
import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from src.annotation.pooling import compute_chunk_key
from src.config import app_config
from src.notion.mirror import extract_page_id
from src.paths import ANNOTATIONS_PATH
from src.retrieval.search_config import SYNC_CONFIG

BACKUP_SUFFIX = ".before-page-ids"


@dataclass
class MigrationReport:
    judgments: int = 0
    migrated: int = 0
    already_migrated: int = 0
    orphaned: list[tuple[str, str]] = field(default_factory=list)
    without_page_id: list[str] = field(default_factory=list)

    def describe(self) -> str:
        lines = [
            f"judgments:                {self.judgments}",
            f"rewritten to page ids:    {self.migrated}",
            f"already on page ids:      {self.already_migrated}",
            f"orphaned (text is gone):  {len(self.orphaned)}",
            f"no page id in the path:   {len(self.without_page_id)}",
        ]
        lines.extend(
            f"  orphaned: {query} — {chunk_key}" for query, chunk_key in self.orphaned
        )
        return "\n".join(lines)


def find_chunk_id_for_text(
    chunks: Sequence[tuple[str, str]], chunk_key: str
) -> str | None:
    """The id of the page's chunk whose text hashes to that judgment's key."""
    for chunk_id, text in chunks:
        if compute_chunk_key(text, "migration", None) == chunk_key:
            return chunk_id
    return None


def migrate_annotations(
    data: dict[str, Any],
    chunks_by_page: Mapping[str, Sequence[tuple[str, str]]],
    paths_by_page: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], MigrationReport]:
    """Point every judgment at the chunk that now holds its text.

    `chunks_by_page` is the synced chunks of each page, as (chunk id, text).
    Anything not found is left untouched, so re-running is safe.
    """
    report = MigrationReport()
    mirror_paths = paths_by_page or {}
    migrated = json.loads(json.dumps(data))
    for query_key, entry in migrated["queries"].items():
        for chunk_key, annotation in entry["annotations"].items():
            report.judgments += 1
            page_id = find_judged_page_id(annotation)
            if page_id is None:
                report.without_page_id.append(chunk_key)
                continue
            new_chunk_id = find_chunk_id_for_text(
                chunks_by_page.get(page_id, ()), chunk_key
            )
            if new_chunk_id is None:
                report.orphaned.append((query_key, chunk_key))
                continue
            if all(
                source.get("chunk_id") == new_chunk_id
                for source in annotation.get("sources", [])
            ):
                report.already_migrated += 1
            else:
                report.migrated += 1
            for source in annotation.get("sources", []):
                source["chunk_id"] = new_chunk_id
            metadata = annotation.setdefault("metadata", {})
            metadata["source"] = page_id
            if page_id in mirror_paths:
                metadata["path"] = mirror_paths[page_id]
    return migrated, report


def find_judged_page_id(annotation: Mapping[str, Any]) -> str | None:
    """The page a judgment was made on, from any chunk id it recorded."""
    for source in annotation.get("sources", []):
        page_id = extract_page_id(str(source.get("chunk_id", "")).split("#")[0])
        if page_id:
            return page_id
    source_path = (annotation.get("metadata") or {}).get("source", "")
    return extract_page_id(str(source_path)) or None


def load_chunks_by_page(
    database_url: str, table: str
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
    """Every synced chunk, grouped by page, plus each page's file in the mirror."""
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            sql.SQL("SELECT id, source, text, metadata FROM {} ORDER BY id").format(
                sql.Identifier(table)
            )
        ).fetchall()
    chunks: dict[str, list[tuple[str, str]]] = {}
    mirror_paths: dict[str, str] = {}
    for chunk_id, source, text, metadata in rows:
        chunks.setdefault(source, []).append((chunk_id, text))
        path = (metadata or {}).get("path")
        if path:
            mirror_paths[source] = path
    return chunks, mirror_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=ANNOTATIONS_PATH)
    parser.add_argument(
        "--table",
        default=SYNC_CONFIG.arms[0].table,
        help="the synced chunk table to look the judged text up in",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report only, write nothing"
    )
    args = parser.parse_args()

    with open(args.annotations, encoding="utf-8") as f:
        data = json.load(f)
    chunks, mirror_paths = load_chunks_by_page(app_config.database_url, args.table)
    migrated, report = migrate_annotations(data, chunks, mirror_paths)
    print(report.describe())

    if args.dry_run:
        print("dry run: nothing written")
        return
    backup = args.annotations.with_suffix(args.annotations.suffix + BACKUP_SUFFIX)
    shutil.copy2(args.annotations, backup)
    with open(args.annotations, "w", encoding="utf-8") as f:
        json.dump(migrated, f, ensure_ascii=False, indent=2)
    print(f"written; the original is at {backup}")


if __name__ == "__main__":
    main()
