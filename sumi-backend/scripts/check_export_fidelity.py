"""Measure the normaliser against the hand-made export, which is its oracle.

Human relevance judgments are joined by a hash of a chunk's text, so if the
sync renders a note even slightly differently from the export, the labels for
that note no longer match anything. The export folder is the only thing that
can say whether that has happened, so this script fetches each exported page
from Notion, renders it the way the sync would, chunks both texts the way the
indexer does, and compares the resulting sequences of chunk hashes.

It only compares pages Notion says were last edited before the export was
made; a page edited since would differ for a reason that has nothing to do
with the normaliser.

    uv run python -m scripts.check_export_fidelity \\
        --export ../data/notion-export-markdown --judged-first --cache-dir .cache

`--cache-dir` keeps each page's raw Notion markdown, so trying a new
normaliser rule re-runs offline instead of spending 2,300 requests again.
"""

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.annotation.pooling import compute_chunk_key
from src.config import app_config
from src.notion.client import NotionClient, NotionError
from src.notion.mirror import extract_page_id
from src.notion.sync import (
    build_link_tables,
    collect_containers,
    collect_listing,
    compute_places,
    render_synced_page,
)
from src.retrieval.chunker import chunk_text
from src.retrieval.cleaner import clean_text

# The export's newest note is dated 2026-08-09, so a page edited after this was
# edited after the export and is expected to differ.
DEFAULT_EDITED_BEFORE = datetime(2026, 8, 10, tzinfo=UTC)
TOP_DIFFERENCES = 10


@dataclass(frozen=True)
class ExportPage:
    """One markdown file from the export, and the Notion page id in its name."""

    page_id: str
    path: Path
    text: str


@dataclass(frozen=True)
class PageComparison:
    page_id: str
    identical: bool
    shares_a_chunk: bool
    first_difference: tuple[str, str] | None


@dataclass
class FidelityReport:
    compared: int = 0
    identical: int = 0
    share_a_chunk: int = 0
    skipped_edited: int = 0
    skipped_missing: int = 0
    failed: int = 0
    differences: Counter[tuple[str, str]] = field(default_factory=Counter)

    def describe(self) -> str:
        def share(count: int) -> str:
            return f"{count}/{self.compared} ({count / max(self.compared, 1):.1%})"

        lines = [
            f"pages compared:              {self.compared}",
            f"identical chunk sequences:   {share(self.identical)}",
            f"at least one identical chunk:{share(self.share_a_chunk)}",
            f"skipped, edited since export:{self.skipped_edited}",
            f"skipped, not in Notion:      {self.skipped_missing}",
            f"failed to fetch:             {self.failed}",
        ]
        if self.differences:
            lines.append("commonest first-differing lines (export | sync):")
            lines.extend(
                f"  x{count:<4} {exported!r} | {synced!r}"
                for (exported, synced), count in self.differences.most_common(
                    TOP_DIFFERENCES
                )
            )
        return "\n".join(lines)


def find_export_pages(export_dir: Path) -> list[ExportPage]:
    """Every exported markdown file whose name ends in a 32-hex Notion page id."""
    pages = []
    for path in sorted(export_dir.rglob("*.md")):
        page_id = extract_page_id(path.stem)
        if page_id:
            pages.append(
                ExportPage(
                    page_id=page_id, path=path, text=path.read_text(encoding="utf-8")
                )
            )
    return pages


def compute_chunk_keys(text: str) -> list[str]:
    """The hashes a note's chunks would be judged under, in order."""
    cleaned = clean_text(text)
    return [compute_chunk_key(chunk, "fidelity", None) for chunk in chunk_text(cleaned)]


def find_first_difference(exported: str, synced: str) -> tuple[str, str] | None:
    """The first line the two renderings disagree on, for the report."""
    export_lines = exported.split("\n")
    sync_lines = synced.split("\n")
    for index in range(max(len(export_lines), len(sync_lines))):
        left = export_lines[index] if index < len(export_lines) else ""
        right = sync_lines[index] if index < len(sync_lines) else ""
        if left != right:
            return left, right
    return None


def compare_page(page_id: str, exported: str, synced: str) -> PageComparison:
    export_keys = compute_chunk_keys(exported)
    sync_keys = compute_chunk_keys(synced)
    return PageComparison(
        page_id=page_id,
        identical=export_keys == sync_keys,
        shares_a_chunk=bool(set(export_keys) & set(sync_keys)),
        first_difference=find_first_difference(exported, synced),
    )


def summarise(comparisons: list[PageComparison]) -> FidelityReport:
    report = FidelityReport(compared=len(comparisons))
    for comparison in comparisons:
        report.identical += comparison.identical
        report.share_a_chunk += comparison.shares_a_chunk
        if not comparison.identical and comparison.first_difference is not None:
            report.differences[comparison.first_difference] += 1
    return report


def load_judged_page_ids(annotations_path: Path) -> set[str]:
    """The page ids the human judgments cover, so they can be checked first."""
    if not annotations_path.exists():
        return set()
    with open(annotations_path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        page_id
        for entry in data.get("queries", {}).values()
        for annotation in entry.get("annotations", {}).values()
        for source in annotation.get("sources", []) or []
        if (page_id := extract_page_id(str(source.get("chunk_id", "")).split("#")[0]))
    }


def order_pages(
    pages: list[ExportPage], judged: set[str], judged_first: bool
) -> list[ExportPage]:
    if not judged_first:
        return pages
    return sorted(pages, key=lambda page: page.page_id not in judged)


def read_cached(cache_dir: Path | None, page_id: str) -> str | None:
    if cache_dir is None:
        return None
    path = cache_dir / f"{page_id}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


def write_cached(cache_dir: Path | None, page_id: str, enhanced: str) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{page_id}.md").write_text(enhanced, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--export", type=Path, default=Path("../data/notion-export-markdown")
    )
    parser.add_argument(
        "--sample", type=int, default=None, help="check only the first N pages"
    )
    parser.add_argument(
        "--judged-first",
        action="store_true",
        help="check the pages the human judgments cover before the rest",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="store each page's raw Notion markdown here, so a normaliser change "
        "can be re-checked offline",
    )
    parser.add_argument(
        "--annotations", type=Path, default=Path("../data/annotations.json")
    )
    args = parser.parse_args()

    pages = order_pages(
        find_export_pages(args.export),
        load_judged_page_ids(args.annotations),
        args.judged_first,
    )
    if args.sample is not None:
        pages = pages[: args.sample]

    client = NotionClient(app_config.notion_token)
    try:
        containers = collect_containers(client)
        listed, _ = collect_listing(client, None)
        objects = {obj.id: obj for obj in [*containers, *listed]}
        places = compute_places(objects)
        titles, mirror_paths = build_link_tables(objects, places)
        schema_orders = {obj.id: obj.schema_order for obj in containers}

        report = FidelityReport()
        comparisons: list[PageComparison] = []
        for page in pages:
            obj = objects.get(page.page_id)
            if obj is None:
                report.skipped_missing += 1
                continue
            if (
                obj.last_edited_time is not None
                and obj.last_edited_time >= DEFAULT_EDITED_BEFORE
            ):
                report.skipped_edited += 1
                continue
            enhanced = read_cached(args.cache_dir, page.page_id)
            if enhanced is None:
                try:
                    enhanced = client.get_page_markdown(page.page_id)
                except NotionError as error:
                    print(f"  {page.page_id}: {error}")
                    report.failed += 1
                    continue
                write_cached(args.cache_dir, page.page_id, enhanced)
            synced = render_synced_page(
                enhanced, obj, places[page.page_id], schema_orders, titles, mirror_paths
            )
            comparisons.append(compare_page(page.page_id, page.text, synced))
    finally:
        client.close()

    summary = summarise(comparisons)
    summary.skipped_edited = report.skipped_edited
    summary.skipped_missing = report.skipped_missing
    summary.failed = report.failed
    print(summary.describe())


if __name__ == "__main__":
    main()
