"""Ingest documents from a data directory into the pgvector index.

Loads .md/.txt files, cleans and chunks them, then embeds and upserts the
chunks with the chosen embedder. Chunk ids are "{source}#{chunk_index}", so
re-running upserts in place.
"""

import argparse
import asyncio
import re
from pathlib import Path

import psycopg
from psycopg import sql
from tqdm import tqdm

from src.config import app_config
from src.retrieval.chunker import chunk_text
from src.retrieval.cleaner import clean_text
from src.retrieval.embedder import (
    BgeM3Embedder,
    GeminiEmbedder,
    QwenEmbedder,
    TitlePrefixEmbedder,
)
from src.retrieval.indexer import Document, PgVectorIndexer


def title_from(path: Path) -> str:
    return re.sub(r"\s*[0-9a-f]{32}$", "", path.stem) or path.stem


def load_documents(data_dir: Path) -> list[Document]:
    documents = []
    files = sorted(p for p in data_dir.rglob("*") if p.suffix in {".md", ".txt"})
    for path in files:
        text = clean_text(path.read_text(encoding="utf-8"))
        if not text:
            continue
        source = str(path.relative_to(data_dir))
        for i, chunk in enumerate(chunk_text(text)):
            documents.append(
                Document(
                    id=f"{source}#{i}",
                    text=chunk,
                    source=source,
                    metadata={"title": title_from(path)},
                )
            )
    return documents


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(app_config.data_dir))
    parser.add_argument(
        "--embedder", choices=["gemini", "qwen", "bge-m3"], default="gemini"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only index the first N chunks"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip chunks whose id is already in the table (resume after quota cutoff)",
    )
    parser.add_argument(
        "--title-prefix",
        action="store_true",
        help="Embed each chunk with its note title prepended, into a *_title table",
    )
    args = parser.parse_args()

    if args.embedder == "gemini":
        embedder = GeminiEmbedder(
            api_key=app_config.gemini_api_key,
            output_dimensionality=app_config.embedding_dimensions,
        )
        dimensions, table = app_config.embedding_dimensions, "chunks"
    elif args.embedder == "qwen":
        embedder = QwenEmbedder()
        dimensions, table = embedder.output_dimensionality, "chunks_qwen"
    else:
        embedder = BgeM3Embedder()
        dimensions, table = embedder.output_dimensionality, "chunks_bge_m3"

    if args.title_prefix:
        embedder = TitlePrefixEmbedder(embedder)
        table = f"{table}_title"

    documents = load_documents(args.data_dir)
    indexer = PgVectorIndexer(
        app_config.database_url, embedder=embedder, dimensions=dimensions, table=table
    )
    await indexer.ensure_schema()
    if args.skip_existing:
        with psycopg.connect(app_config.database_url) as conn:
            rows = conn.execute(
                sql.SQL("SELECT id FROM {}").format(sql.Identifier(table))
            ).fetchall()
        existing = {row[0] for row in rows}
        documents = [doc for doc in documents if doc.id not in existing]
    if args.limit is not None:
        documents = documents[: args.limit]
    print(f"{len(documents)} chunks to index from {args.data_dir} into {table!r}")
    batch_size = 50
    for start in tqdm(range(0, len(documents), batch_size), desc="indexing"):
        await indexer.index(documents[start : start + batch_size])
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
