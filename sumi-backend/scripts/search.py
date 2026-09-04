"""Search the notes: `uv run python -m scripts.search "query" [--top-k 10]`."""

import argparse
import asyncio

from src.retrieval.retrieve import retrieve

SNIPPET_CHARS = 200


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    results = await retrieve(args.query, top_k=args.top_k)
    for rank, row in enumerate(results, start=1):
        metadata = row.get("metadata") or {}
        title = metadata.get("title", "")
        path = metadata.get("path") or row["source"]
        snippet = " ".join(row["text"].split())[:SNIPPET_CHARS]
        print(f"{rank:>2}. {row['score']:.4f}  {title}")
        print(f"    {path}")
        print(f"    {snippet}\n")


if __name__ == "__main__":
    asyncio.run(main())
