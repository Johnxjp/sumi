# AGENTS.md

Backend for "sumi", a RAG system over a personal Notion export. The notes live
outside the repo at `../data/notion-export-markdown` (configurable via
`data_dir`); eval datasets are written to `../data/datasets/`.

## Commands

Python 3.12, managed with [uv](https://docs.astral.sh/uv/).

| Task | Command |
|------|---------|
| Install deps | `uv sync` |
| Run all tests | `uv run pytest` |
| Run one test | `uv run pytest tests/test_pooling.py::test_pool_merges_same_text_across_retrievers` |
| Lint + format | `uv run ruff check . --fix && uv run ruff format .` |
| Agent REPL | `uv run main.py` |
| Ingest notes into pgvector | `uv run python -m scripts.ingest --embedder qwen` (or `gemini`; `--skip-existing` resumes) |
| Annotation UI | `uv run uvicorn src.annotation.app:app --reload --port 8765` → http://localhost:8765 |
| Generate eval sample/queries | `uv run python -m evals.generate_notes_sample`, then `uv run python -m evals.generate_queries` |

Scripts must be run from the repo root with `-m` (they use absolute `src.` imports).

## Configuration

Two separate pydantic-settings objects, both reading `.env`:

- `src/config.py` → `app_config` (data dir, OpenRouter/Gemini keys, `DATABASE_URL`
  for pgvector, BreadBowl creds). It sets `extra="forbid"`, so **every variable in
  `.env` must have a corresponding field** — adding an env var without a field
  breaks all imports of `app_config` at import time.
- `evals/config.py` → settings for the eval-generation scripts (model, temperature,
  concurrency).

## Architecture

Four loosely-coupled parts:

**1. Agent CLI** (`main.py` → `src/agent.py` + `src/tools/`): a terminal REPL
running an OpenRouter tool-calling agent. Its tools (`src/tools/file.py`,
registered via `src/tools/registry.py`) are filesystem reads over the notes
directory — `read_file`, directory listing, ripgrep search — sandboxed to
`data_dir`. It does **not** yet use the vector retrieval stack.

**2. Retrieval pipeline** (`src/retrieval/`): the ingestion flow is
`cleaner.clean_text` (NFKC/whitespace normalization) → `chunker.chunk_text`
(recursive splitter, 2000-char max / 200 min / 50 overlap) → an `Embedder` →
an `Indexer`. Two `Embedder` implementations in `embedder.py`: `GeminiEmbedder`
(API, 768-dim, free-tier rate-limit handling) and `QwenEmbedder` (local
sentence-transformers, 1024-dim, lazy model load). Two `Indexer` implementations
in `indexer.py`: `PgVectorIndexer` (Postgres + pgvector; **async** `index`/`search`,
cosine similarity) and the legacy `BreadBowlIndexer` (external HTTP API, sync).
Each embedder gets its own table — `chunks` (gemini) and `chunks_qwen` — created
by `ensure_schema()`. Chunk ids are `"{source}#{chunk_index}"`, so re-running
`scripts/ingest.py` upserts in place.

**3. Annotation tool** (`src/annotation/` + `static/`): FastAPI backend plus a
single vanilla-JS page for labeling retrieval relevance (2 = highly relevant,
1 = partially, 0 = not). A query fans out to every retriever declared in
`retrievers.json` (types: `pgvector`, `static`, `breadbowl` — built in
`retrievers.py`); results are pooled and deduplicated by a hash of
whitespace-normalized chunk text (`pooling.py`), and annotated **blind** — the UI
never shows which retriever returned a chunk, but per-retriever rank/score
provenance is stored for later metrics. Labels persist to `annotations.json`
(`store.py`, atomic writes), keyed by case/whitespace-normalized query;
re-running a query pre-fills existing scores. `search()` may be sync or async
per retriever — the endpoint awaits when needed.

**4. Evals** (`evals/`): standalone scripts that sample notes and use an LLM
(via OpenRouter) to generate test queries with their source passages —
the input dataset that the annotation tool then scores against.

## Conventions

- Absolute imports (`from src.retrieval.indexer import ...`).
- Tests live in `tests/`, pytest, logic-level (no HTTP/framework tests).
- `secrets/` and `.env` are gitignored; `annotations.json` is data, safe to commit.
