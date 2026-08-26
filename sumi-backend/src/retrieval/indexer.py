from abc import ABC, abstractmethod
from typing import Any

import psycopg
import requests
from pgvector import Vector
from pgvector.psycopg import register_vector_async
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from src.retrieval.embedder import Embedder


class Document(BaseModel):
    id: str
    text: str
    source: str
    metadata: dict[str, Any]


class Indexer(ABC):
    @abstractmethod
    def index(self, documents: list[str]):
        raise NotImplementedError("Subclasses must implement the index method.")

    @abstractmethod
    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError("Subclasses must implement the search method.")


class BreadBowlIndexer(Indexer):
    def __init__(self, api_base_url: str, api_key: str, index_id: str | None = None):
        self.api_base_url = api_base_url
        self.api_key = api_key
        self.index_id = index_id
        self._index_metadata = None

    def create_index(self):
        # Implement the logic to create an index in BreadBowl using the API
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = {"name": "production", "text_retention": "none"}  # Customize as needed
        response = requests.post(
            f"{self.api_base_url}/v1/indexes", headers=headers, json=data
        )
        if response.status_code == 200:
            self.index_id = response.json().get("id")
            self._index_metadata = response.json()
            print("Index created successfully.")
            return self.index_id

        raise ValueError(
            f"Failed to create index: {response.status_code} - {response.text}"
        )

    def index(self, documents: list[Document]) -> list[tuple[str, str]]:
        """Returns failed documents"""
        if not self.index_id:
            raise ValueError("Index ID is not set. Please create an index first.")

        max_documents_per_request = 50  # Set by API
        url = f"{self.api_base_url}/v1/indexes/{self.index_id}/documents"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        failed_documents = []
        for batch_start in range(0, len(documents), max_documents_per_request):
            batch = documents[batch_start : batch_start + max_documents_per_request]
            data = {
                "documents": [
                    {
                        "doc_id": str(doc.id),
                        "text": doc.text,
                        "metadata": {"source": doc.source, **doc.metadata},
                    }
                    for doc in batch
                ]
            }
            response = requests.post(
                url,
                headers=headers,
                json=data,
            )
            response = response.json()
            if len(response["failed"]):
                failed_documents.extend(
                    (response["failed"]["doc_id"], response["failed"]["error"])
                )

        return failed_documents

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Search the index for documents matching the query."""
        if not self.index_id:
            raise ValueError("Index ID is not set. Please create an index first.")

        url = f"{self.api_base_url}/v1/indexes/{self.index_id}/search"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data: dict[str, Any] = {"query": query}
        if top_k is not None:
            data["limit"] = top_k

        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            results = response.json().get("results", [])
            return results[:top_k] if top_k is not None else results

        raise ValueError(
            f"Failed to search index: {response.status_code} - {response.text}"
        )


class PgVectorIndexer(Indexer):
    """Stores chunk embeddings in Postgres with pgvector, embedding client-side."""

    def __init__(
        self,
        database_url: str,
        embedder: Embedder,
        dimensions: int = 768,
        table: str = "chunks",
    ):
        self.database_url = database_url
        self.embedder = embedder
        self.dimensions = dimensions
        self.table = table

    async def ensure_schema(self) -> None:
        """Create the extension, table, and HNSW index if they don't exist."""
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {} ("
                    "id text PRIMARY KEY, "
                    "text text NOT NULL, "
                    "source text NOT NULL, "
                    "metadata jsonb NOT NULL DEFAULT '{{}}', "
                    "embedding vector({}) NOT NULL)"
                ).format(sql.Identifier(self.table), sql.Literal(self.dimensions))
            )
            await conn.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (source)").format(
                    sql.Identifier(f"{self.table}_source_idx"),
                    sql.Identifier(self.table),
                )
            )
            await conn.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {} ON {} "
                    "USING hnsw (embedding vector_cosine_ops)"
                ).format(
                    sql.Identifier(f"{self.table}_embedding_idx"),
                    sql.Identifier(self.table),
                )
            )

    async def index(self, documents: list[Document]) -> list[tuple[str, str]]:
        """Embed and upsert documents. All-or-nothing: raises on failure,
        so the returned failed-documents list is always empty."""
        if not documents:
            return []
        titles = [str(doc.metadata.get("title", "none")) for doc in documents]
        embeddings = await self.embedder.embed_documents(
            [doc.text for doc in documents], titles=titles
        )
        async with await self._connect() as conn, conn.cursor() as cur:
            await cur.executemany(
                sql.SQL(
                    "INSERT INTO {} (id, text, source, metadata, embedding) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text, "
                    "source = EXCLUDED.source, "
                    "metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding"
                ).format(sql.Identifier(self.table)),
                [
                    (
                        doc.id,
                        doc.text,
                        doc.source,
                        Jsonb(doc.metadata),
                        Vector(embedding),
                    )
                    for doc, embedding in zip(documents, embeddings, strict=True)
                ],
            )
        return []

    async def search(
        self, query: str, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        """Return the closest chunks by cosine similarity, best first."""
        query_vector = Vector(await self.embedder.embed_query(query))
        async with await self._connect() as conn:
            cursor = await conn.execute(
                sql.SQL(
                    "SELECT id, text, source, metadata, 1 - (embedding <=> %s) AS score "
                    "FROM {} ORDER BY embedding <=> %s LIMIT %s"
                ).format(sql.Identifier(self.table)),
                (query_vector, query_vector, top_k if top_k is not None else 10),
            )
            rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "text": row[1],
                "source": row[2],
                "metadata": row[3],
                "score": float(row[4]),
            }
            for row in rows
        ]

    async def _connect(self) -> psycopg.AsyncConnection:
        conn = await psycopg.AsyncConnection.connect(self.database_url)
        await register_vector_async(conn)
        return conn
