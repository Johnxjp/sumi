"""Drop generated queries whose note is not in a frozen eval corpus.

    uv run python -m scripts.prune_generated_queries \\
        --corpus ../data/eval-corpus-2026-09-05/corpus

The generated query set was written from the notes as they were in August. A
query is scored by whether any chunk of the note it came from is retrieved, so
a query whose note has since been deleted in Notion can never be answered: it
counts as a miss in every run and drags every score down for no reason.

The note is identified by the Notion page id at the end of its file name, so a
note that moved or was renamed is still found. The original file is copied
beside the pruned one before anything is written.
"""

import argparse
import json
import shutil
from pathlib import Path

from src.notion.mirror import extract_page_id
from src.paths import DATA_DIR

BACKUP_SUFFIX = ".before-prune"


def find_corpus_page_ids(corpus_dir: Path) -> set[str]:
    ids = set()
    for path in corpus_dir.rglob("*.md"):
        page_id = extract_page_id(path.stem)
        if page_id:
            ids.add(page_id)
    return ids


def partition_queries(
    queries: list[dict], page_ids: set[str]
) -> tuple[list[dict], list[dict]]:
    """(queries whose note is in the corpus, queries whose note is gone)."""
    kept, dropped = [], []
    for query in queries:
        page_id = extract_page_id(Path(query.get("source_file", "")).stem)
        (kept if page_id and page_id in page_ids else dropped).append(query)
    return kept, dropped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path, required=True, help="the frozen corpus/ folder"
    )
    parser.add_argument(
        "--queries", type=Path, default=DATA_DIR / "datasets/queries.json"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report only, write nothing"
    )
    args = parser.parse_args()

    page_ids = find_corpus_page_ids(args.corpus)
    with open(args.queries, encoding="utf-8") as f:
        data = json.load(f)
    kept, dropped = partition_queries(data["queries"], page_ids)

    print(f"corpus documents: {len(page_ids)}")
    print(f"queries:          {len(data['queries'])}")
    print(f"  kept:           {len(kept)}")
    print(f"  dropped:        {len(dropped)}  (their note is not in the corpus)")
    for query in dropped[:5]:
        print(f"    {query['source_file']}")
    if len(dropped) > 5:
        print(f"    ... and {len(dropped) - 5} more")

    if args.dry_run:
        print("dry run: nothing written")
        return
    if not dropped:
        print("nothing to drop")
        return

    backup = args.queries.with_suffix(args.queries.suffix + BACKUP_SUFFIX)
    shutil.copyfile(args.queries, backup)
    data["queries"] = kept
    with open(args.queries, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {args.queries}; original copied to {backup.name}")


if __name__ == "__main__":
    main()
