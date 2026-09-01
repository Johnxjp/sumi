"""Build the lexical index from an already-ingested dense table.

`uv run python -m scripts.build_fts` — copies chunk text, source and metadata
into chunks_fts, where a generated tsvector column indexes them. Idempotent.
"""

import argparse
import asyncio

from src.config import app_config
from src.retrieval.lexical import PgFtsIndexer


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-table", default="chunks_qwen")
    parser.add_argument("--table", default="chunks_fts")
    args = parser.parse_args()

    indexer = PgFtsIndexer(app_config.database_url, table=args.table)
    await indexer.ensure_schema()
    count = await indexer.sync_from(args.source_table)
    print(f"synced {count} chunks from {args.source_table!r} into {args.table!r}")


if __name__ == "__main__":
    asyncio.run(main())
