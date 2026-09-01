"""Postgres full-text search over the same chunks as the dense tables."""

from typing import Any

import psycopg
from psycopg import sql

from src.retrieval.indexer import Indexer


class PgFtsIndexer(Indexer):
    """A lexical arm backed by a standalone tsvector table.

    The table holds its own copy of the chunk text so it can be rebuilt
    without re-embedding, and shares chunk ids with the dense tables so
    fusion can deduplicate across arms. Titles are weighted above body text.
    """

    def __init__(
        self, database_url: str, table: str = "chunks_fts", max_df: float = 0.15
    ):
        self.database_url = database_url
        self.table = table
        # Terms in more than this fraction of chunks ("make", "people",
        # "product" in a personal note corpus) say nothing about which chunk
        # is wanted, and matching them drags in thousands of candidates.
        self.max_df = max_df

    async def ensure_schema(self) -> None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {} ("
                    "id text PRIMARY KEY, "
                    "text text NOT NULL, "
                    "source text NOT NULL, "
                    "metadata jsonb NOT NULL DEFAULT '{{}}', "
                    "tsv tsvector GENERATED ALWAYS AS ("
                    "setweight(to_tsvector('english', "
                    "coalesce(metadata->>'title', '')), 'A') || "
                    "setweight(to_tsvector('english', text), 'B')) STORED)"
                ).format(sql.Identifier(self.table))
            )
            await conn.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} USING GIN (tsv)").format(
                    sql.Identifier(f"{self.table}_tsv_idx"), sql.Identifier(self.table)
                )
            )

    async def sync_from(self, source_table: str) -> int:
        """Copy ids, text, source and metadata from a dense table. Idempotent."""
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cursor = await conn.execute(
                sql.SQL(
                    "INSERT INTO {} (id, text, source, metadata) "
                    "SELECT id, text, source, metadata FROM {} "
                    "ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text, "
                    "source = EXCLUDED.source, metadata = EXCLUDED.metadata"
                ).format(sql.Identifier(self.table), sql.Identifier(source_table))
            )
            return cursor.rowcount

    def index(self, documents: list[str]):
        raise NotImplementedError("Populate the FTS table with sync_from().")

    async def search(
        self, query: str, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        """Rank by IDF-weighted term coverage, ties broken by ts_rank_cd.

        Terms are OR-ed, not AND-ed: requiring every term (what plainto_ and
        websearch_to_tsquery do) returns nothing for question-shaped queries,
        which is most of them. Ranking then has to make up for the recall it
        buys, and ts_rank_cd alone cannot — it has no notion of how rare a
        term is, so a chunk repeating a common word outranks the one chunk
        that matches a rare name. Summing the IDF of the query terms a chunk
        covers restores that, and the ts_rank_cd fraction added on top orders
        chunks that cover the same terms by frequency and proximity.

        Terms above max_df are dropped first, unless no term that occurs at
        all is below it, in which case they all stay and the query is
        answered on frequency alone. A query of nothing but stopwords parses
        to an empty tsquery and matches nothing, which is the right answer.
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cursor = await conn.execute(
                sql.SQL(
                    "WITH total AS (SELECT count(*)::float AS docs FROM {table}), "
                    "terms AS ("
                    "  SELECT unnest(string_to_array(replace("
                    "           plainto_tsquery('english', %(query)s)::text,"
                    "           ' & ', '||'), '||'))::tsquery AS t), "
                    "counted AS ("
                    "  SELECT terms.t, (SELECT count(*) FROM {table} d"
                    "                   WHERE d.tsv @@ terms.t)::float AS df"
                    "  FROM terms WHERE terms.t::text <> ''), "
                    "kept AS ("
                    "  SELECT counted.t, ln(1 + total.docs / (1 + counted.df)) AS idf"
                    "  FROM counted, total"
                    "  WHERE counted.df <= total.docs * %(max_df)s"
                    "     OR NOT EXISTS (SELECT 1 FROM counted c2, total t2"
                    "                    WHERE c2.df > 0"
                    "                      AND c2.df <= t2.docs * %(max_df)s)), "
                    "matcher AS (SELECT string_agg(t::text, ' | ')::tsquery AS q FROM kept) "
                    "SELECT c.id, c.text, c.source, c.metadata,"
                    "  (SELECT coalesce(sum(kept.idf), 0) FROM kept WHERE c.tsv @@ kept.t)"
                    "  + ts_rank_cd(c.tsv, matcher.q)"
                    "    / (1 + ts_rank_cd(c.tsv, matcher.q)) AS score "
                    "FROM {table} c, matcher WHERE c.tsv @@ matcher.q "
                    "ORDER BY score DESC, c.id LIMIT %(top_k)s"
                ).format(table=sql.Identifier(self.table)),
                {
                    "query": query,
                    "max_df": self.max_df,
                    "top_k": top_k if top_k is not None else 10,
                },
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
