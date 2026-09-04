"""Check that judgments join back onto fresh retrieval results.

`uv run python -m evals.retrieval.selftest` — re-runs the arm the annotation
pool was built from and asserts every judgment it contributed is matched again
by the qrels join. If this fails, every NDCG in every run is wrong, so run it
before trusting a new number.

A judgment is a score a person gave to one chunk of text. It is joined to a
retrieved chunk by a hash of that text, so it can stop matching for two very
different reasons: the join broke, or the note was edited in Notion since it
was labelled and no longer contains that text. This checks which by looking
for the judged text among the page's current chunks. Only the first is a
failure; the second is reported and expected to grow as the workspace moves on.

It also reports judged coverage, which is a property of how much labelling has
been done, not of the join: the pool was labelled from the top down and left a
tail unlabelled, so coverage below 1.0 is expected and only means the reported
NDCG is a lower bound.
"""

import argparse
import asyncio
import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path

import psycopg
from psycopg import sql

from evals.retrieval import paths
from evals.retrieval.qrels import GradedQuery, load_graded_qrels, match_chunk_key
from src.annotation.pooling import compute_chunk_key
from src.annotation.store import normalize_query
from src.config import app_config
from src.notion.mirror import extract_page_id
from src.retrieval.retrieve import HybridRetriever
from src.retrieval.search_config import (
    BGE_ARM,
    BGE_NOTION_ARM,
    QWEN_ARM,
    QWEN_NOTION_ARM,
    RetrievalConfig,
)

POOL_DEPTH = 10
POOL_ARMS = {
    "export": {"qwen": QWEN_ARM, "bge-m3": BGE_ARM},
    "notion": {"qwen": QWEN_NOTION_ARM, "bge-m3": BGE_NOTION_ARM},
}


def find_pooled_chunk_keys(
    path: Path, retriever: str, max_rank: int
) -> dict[str, set[str]]:
    """Judgments this retriever contributed to the pool, per normalized query.

    Keyed by chunk key — the hash of the judged text — rather than by chunk id,
    because ids changed when notes started coming from Notion and the text did
    not.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    pooled: dict[str, set[str]] = {}
    for query_key, entry in data["queries"].items():
        pooled[normalize_query(query_key)] = {
            chunk_key
            for chunk_key, annotation in entry["annotations"].items()
            for source in annotation.get("sources", [])
            if source["retriever"] == retriever and source["rank"] <= max_rank
        }
    return pooled


def find_page_ids(qrel: GradedQuery, chunk_keys: Iterable[str]) -> dict[str, str]:
    """The page each judgment was made on, from a chunk id it recorded."""
    pages = {}
    for chunk_key in chunk_keys:
        chunk_id = qrel.get_chunk_id(chunk_key)
        if chunk_id is None:
            continue
        page_id = extract_page_id(str(chunk_id).split("#")[0])
        if page_id:
            pages[chunk_key] = page_id
    return pages


def split_misses(
    missed: Iterable[str],
    page_by_chunk_key: Mapping[str, str],
    keys_by_page: Mapping[str, set[str]],
) -> tuple[list[str], list[str]]:
    """Sort unmatched judgments into join failures and pages that changed.

    The judged text still being among the page's chunks means retrieval or the
    join is at fault. The text having gone means the note was edited since it
    was labelled, which is not a fault.
    """
    failures, changed = [], []
    for chunk_key in sorted(missed):
        page_id = page_by_chunk_key.get(chunk_key)
        if page_id is None or chunk_key in keys_by_page.get(page_id, set()):
            failures.append(chunk_key)
        else:
            changed.append(chunk_key)
    return failures, changed


def load_chunk_keys_by_page(
    database_url: str, table: str, page_ids: Iterable[str]
) -> dict[str, set[str]]:
    """The hashes of every chunk each of those pages currently has."""
    ids = sorted(set(page_ids))
    if not ids:
        return {}
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            sql.SQL("SELECT source, text FROM {} WHERE source = ANY(%s)").format(
                sql.Identifier(table)
            ),
            (ids,),
        ).fetchall()
    keys: dict[str, set[str]] = {}
    for source, text in rows:
        keys.setdefault(source, set()).add(compute_chunk_key(text, "selftest", None))
    return keys


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retriever", choices=["qwen", "bge-m3"], default="qwen")
    parser.add_argument(
        "--corpus",
        choices=sorted(POOL_ARMS),
        default="export",
        help="which tables to check: the export-built ones or the Notion-synced ones",
    )
    args = parser.parse_args()

    arm = POOL_ARMS[args.corpus][args.retriever]
    qrels = load_graded_qrels(paths.ANNOTATIONS_PATH)
    pooled = find_pooled_chunk_keys(paths.ANNOTATIONS_PATH, args.retriever, POOL_DEPTH)
    retriever = HybridRetriever(RetrievalConfig(arms=(replace(arm, depth=POOL_DEPTH),)))

    checked = 0
    failures: list[str] = []
    changed_pages: list[str] = []
    coverage: list[float] = []
    for query_key, qrel in sorted(qrels.items()):
        rows = await retriever.retrieve(qrel.query_text, top_k=POOL_DEPTH)
        matched = {
            key for row in rows if (key := match_chunk_key(qrel, row)) is not None
        }
        checked += len(pooled[query_key])
        missed = pooled[query_key] - matched
        pages = find_page_ids(qrel, missed)
        keys_by_page = load_chunk_keys_by_page(
            app_config.database_url, arm.table, pages.values()
        )
        query_failures, query_changed = split_misses(missed, pages, keys_by_page)
        failures.extend(f"{query_key}: {key}" for key in query_failures)
        changed_pages.extend(f"{query_key}: {key}" for key in query_changed)
        if rows:
            coverage.append(len(matched) / len(rows))

    print(
        f"judgments contributed by {args.retriever} at rank <= {POOL_DEPTH}: {checked}"
    )
    print(
        f"mean judged coverage of the fresh top-{POOL_DEPTH}: "
        f"{sum(coverage) / len(coverage):.3f}"
    )
    print(
        f"judgments whose page changed since labelling: {len(changed_pages)} "
        "(reported, not a failure)"
    )
    if failures:
        print(f"\nFAILED — {len(failures)} judgments did not join back:")
        for failure in failures[:20]:
            print(f"  {failure}")
        raise SystemExit(1)
    print("OK — every pooled judgment joined back, or its page has changed.")


if __name__ == "__main__":
    asyncio.run(main())
