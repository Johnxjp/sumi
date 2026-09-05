# sumi-backend

Backend for "sumi", a RAG system over a personal Notion workspace, with a terminal
agent (note search, filesystem and read-only Gmail tools) and a retrieval pipeline
into pgvector.

## Run

```
uv sync
uv run main.py
```

Talk to the same agent in a browser, with replies streamed: start the chat
backend here, then the page in `../sumi-frontend` (see its README):

```
uv run uvicorn src.chat.app:app --port 8766
```

Search the notes directly:

```
uv run python -m scripts.search "what does napoleon say about leadership"
```

See `../AGENTS.md` for the full command reference (ingestion, evals, linting, etc.)
and architecture notes.

## Annotation app

A FastAPI + vanilla-JS tool for labeling retrieval relevance, used to build eval
data for the retrieval pipeline.

**Spin up:**

```
uv run uvicorn src.annotation.app:app --reload --port 8765
```

Then open http://localhost:8765.

**How it works:** you submit a query in the UI; it fans out to every retriever
declared in `src/annotation/config.py` (the `qwen` and `bge-m3` embedding tables
plus the `chunks_fts` lexical index). Results are pooled and deduplicated
by normalized chunk text, then shown **blind** — you don't see which retriever
returned which chunk. You label each result 2 (highly relevant), 1 (partially),
or 0 (not relevant).

**Data:**

- Notes come from the folder `DATA_DIR` points at. The tables the annotation
  app pools were built from `../data/notion-export-markdown`, a hand-made
  export, by `scripts/ingest.py`. A sync straight from Notion
  (`scripts/sync.py`) is built but not switched on — see
  `../docs/plans/active/notion-sync.md`.
- Labels are saved to `../data/annotations.json`, keyed by query, including
  per-retriever rank/score provenance for later metrics.
