"""Sync the notes from Notion: `uv run python -m scripts.sync [--full]`.

With no flags this is an incremental run: it walks the listing of pages newest
edit first and stops at the watermark, the last successful run's start time
less ten minutes, so a day with no edits costs one request.

Exits non-zero when the run failed or any page failed, so a scheduler notices.
"""

import argparse
import asyncio

from src.notion.sync import run_sync


def print_progress(done: int, total: int) -> None:
    print(f"  {done}/{total} pages", end="\r", flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="walk the whole listing and remove pages that are gone from Notion",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="re-fetch and re-render every listed page, ignoring stored timestamps "
        "(what to run after changing the normaliser)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list and diff only: print what would change and touch nothing",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="index at most N pages, newest first, and delete nothing (a smoke run)",
    )
    parser.add_argument(
        "--mirror-only",
        action="store_true",
        help="rebuild the notes folder from the database, with no network access",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print progress while fetching"
    )
    args = parser.parse_args()

    report = await run_sync(
        mode="full" if args.full else "incremental",
        reindex=args.reindex,
        limit=args.limit,
        dry_run=args.dry_run,
        mirror_only=args.mirror_only,
        on_progress=print_progress if args.verbose else None,
    )
    if args.verbose:
        print()
    print(report.describe())
    if report.status != "ok" or report.pages_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
