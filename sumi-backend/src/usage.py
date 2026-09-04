"""A log of what the agent searched for, and what came back.

One line of JSON per `search_notes` call, appended to
`data/usage/searches.jsonl`. It records both queries: the message the user
typed, and the query the agent rewrote it into before searching. The agent is
told to search with the words a note would contain, so the two differ — "What
did I write in my personal vision?" becomes "personal vision".

This is usage data, not an evaluation record. Nothing scores it. It is kept so
that real queries, and the rewrites the agent chose, can be labelled and turned
into an eval set later, instead of inventing queries by hand.

`corpus_version` is the date the notes were last synced from Notion, so a line
can be read against the corpus it was answered from. Only one corpus is stored,
so this is a label, not a pointer to a snapshot.
"""

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from src.config import app_config
from src.paths import DATA_DIR

logger = logging.getLogger(__name__)

USAGE_PATH = DATA_DIR / "usage" / "searches.jsonl"
RUNS_TABLE = "notion_sync_runs"

# The message the user typed, set by the agent for the length of one turn. The
# search tool is called by the model, which never sees the original wording, so
# the two queries can only meet here.
current_user_query: ContextVar[str | None] = ContextVar(
    "current_user_query", default=None
)


@lru_cache(maxsize=1)
def get_corpus_version(database_url: str | None = None) -> str:
    """The date of the last successful sync, or today's when nothing has synced.

    Cached: it is a label on a log line, and every search would otherwise open
    a connection to read a value that changes once a sync.
    """
    url = database_url or app_config.database_url
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            row = conn.execute(
                sql.SQL("SELECT max(started_at) FROM {} WHERE status = 'ok'").format(
                    sql.Identifier(RUNS_TABLE)
                )
            ).fetchone()
    except psycopg.Error:
        row = None
    if row and row[0]:
        return row[0].date().isoformat()
    return datetime.now(UTC).date().isoformat()


def build_search_record(
    agent_query: str,
    chunks: list[dict[str, Any]],
    retriever_version: str,
    corpus_version: str,
    user_query: str | None = None,
) -> dict[str, Any]:
    return {
        "query_id": f"q_{uuid.uuid4().hex[:8]}",
        "logged_at": datetime.now(UTC).isoformat(),
        "user_query": user_query,
        "agent_query": agent_query,
        "corpus_version": corpus_version,
        "retriever_version": retriever_version,
        "results": [
            {"chunk_id": chunk["chunk_id"], "rank": chunk["rank"]} for chunk in chunks
        ],
    }


def append_record(record: dict[str, Any], path: Path = USAGE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def record_search(
    agent_query: str,
    chunks: list[dict[str, Any]],
    retriever_version: str,
    path: Path | None = None,
) -> None:
    """Log one search. A logging failure must never fail the user's search."""
    try:
        append_record(
            build_search_record(
                agent_query=agent_query,
                chunks=chunks,
                retriever_version=retriever_version,
                corpus_version=get_corpus_version(),
                user_query=current_user_query.get(),
            ),
            path if path is not None else USAGE_PATH,
        )
    except OSError as error:
        logger.warning("could not write the usage log: %s", error)
