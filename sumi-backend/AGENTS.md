# AGENTS.md

Backend for "sumi", a RAG system over a personal Notion export. The notes live
outside the repo at `../data/notion-export-markdown` (configurable via
`data_dir`); eval datasets are written to `../data/datasets/`.

## Commands

Python 3.12, managed with [uv](https://docs.astral.sh/uv/).

- **Install deps:** `uv sync`
- **Run all tests:** `uv run pytest`
- **Run one test:** `uv run pytest tests/test_pooling.py::test_pool_merges_same_text_across_retrievers`
- **Lint + format:** `uv run ruff check . --fix && uv run ruff format .`
- **Agent REPL:** `uv run main.py`
- **Gmail MCP server (optional, for Gmail tools):** `./scripts/run_gmail_mcp.sh`, then verify with `uv run python -m scripts.gmail_smoke`
- **Ingest notes into pgvector:** `uv run python -m scripts.ingest --embedder qwen` (or `gemini`; `--skip-existing` resumes)
- **Annotation UI:** `uv run uvicorn src.annotation.app:app --reload --port 8765` → http://localhost:8765
- **Generate eval sample/queries:** `uv run python -m evals.generate_notes_sample`, then `uv run python -m evals.generate_queries`

Scripts must be run from the repo root with `-m` (they use absolute `src.` imports).

## Configuration

Two separate pydantic-settings objects, both reading `.env`:

- `src/config.py` → `app_config` (data dir, OpenRouter/Gemini keys, `DATABASE_URL`
  for pgvector, BreadBowl creds). It sets `extra="forbid"`, so **every variable in
  `.env` must have a corresponding field** — adding an env var without a field
  breaks all imports of `app_config` at import time.
- `evals/config.py` → settings for the eval-generation scripts (model, temperature,
  concurrency).

`src/annotation/config.py` is plain Python, not pydantic-settings (no env vars):
the retriever declarations and annotations-file path for the annotation tool.

`secrets/` and `.env` are gitignored.

## Architecture

Four loosely-coupled parts:

**1. Agent CLI** (`main.py` → `src/agent.py` + `src/tools/`): a terminal REPL
running an OpenRouter tool-calling agent. Its tools (`src/tools/file.py`,
registered via `src/tools/registry.py`) are filesystem reads over the notes
directory — `read_file`, directory listing, ripgrep search — sandboxed to
`data_dir`. It does **not** yet use the vector retrieval stack.

Read-only Gmail tools are added at startup via MCP: `src/mcp_client.py` is a
generic sync client for any streamable-HTTP MCP server (provider-agnostic, as is
`src/tools/mcp.py`, which discovers tools, filters them against an allowlist,
and registers them); `src/tools/gmail.py` wires it to a locally-run
[workspace-mcp](https://github.com/taylorwilsdon/google_workspace_mcp) server
(`scripts/run_gmail_mcp.sh`, pinned version, `--read-only`, Google OAuth handled
server-side with only the `gmail.readonly` scope). If the server isn't running,
the REPL degrades gracefully to filesystem tools only. Adding another provider
(e.g. Outlook) = a new allowlist + one `register_mcp_tools` call.

**2. Retrieval pipeline** (`src/retrieval/`): the ingestion flow is
`cleaner.clean_text` (NFKC/whitespace normalization) → `chunker.chunk_text`
(recursive splitter, 2000-char max / 200 min / 50 overlap) → an `Embedder` →
an `Indexer`. Three `Embedder` implementations in `embedder.py`: `GeminiEmbedder`
(API, 768-dim, free-tier rate-limit handling) plus `QwenEmbedder` and
`BgeM3Embedder` (local sentence-transformers, 1024-dim, lazy model load, shared
`SentenceTransformerEmbedder` base). Every embedder takes `max_seq_length`
(tokens) and an `overflow_strategy` (`chunking-average` default / `truncate` /
`barbell`) on init; over-length inputs are handled in the `Embedder` base class,
measured with the model tokenizer when available, else a ~3 chars/token proxy.
Two `Indexer` implementations in `indexer.py`: `PgVectorIndexer` (Postgres +
pgvector; **async** `index`/`search`, cosine similarity) and the legacy
`BreadBowlIndexer` (external HTTP API, sync). Each embedder gets its own table —
`chunks` (gemini), `chunks_qwen` and `chunks_bge_m3` — created by
`ensure_schema()`. Chunk ids are `"{source}#{chunk_index}"`, so re-running
`scripts/ingest.py` upserts in place.

**3. Annotation tool** (`src/annotation/` + `static/`): FastAPI backend plus a
single vanilla-JS page for labeling retrieval relevance (2 = highly relevant,
1 = partially, 0 = not). A query fans out to every retriever declared in
`config.py` (types: `pgvector`, `static`, `breadbowl` — built in
`retrievers.py`); results are pooled and deduplicated by a hash of
whitespace-normalized chunk text (`pooling.py`), and annotated **blind** — the UI
never shows which retriever returned a chunk, but per-retriever rank/score
provenance is stored for later metrics. Labels persist to `../data/annotations.json`
(`store.py`, atomic writes), keyed by case/whitespace-normalized query;
re-running a query pre-fills existing scores. `search()` may be sync or async
per retriever — the endpoint awaits when needed.

**4. Evals** (`evals/`): standalone scripts that sample notes and use an LLM
(via OpenRouter) to generate test queries with their source passages —
the input dataset that the annotation tool then scores against.

## Coding Standards

- **Always format and check Python files with ruff immediately after writing or
  editing them:** `uv run ruff format <file_path>` and
  `uv run ruff check --fix <file_path>`. Do this for every Python file you create
  or modify, before moving on to the next step.
- No `assert` in production code.
- **Comment sparingly — code says *what*, comments say *why*.** Add a comment only
  when the reasoning is non-obvious and cannot be carried by a clear name or the
  code itself. Do not write narrating comments that restate the next line, do not
  pad logic with multi-line prose, and do not repeat the same rationale at several
  sites — put one concise note at the source of truth and let the others stand on
  their own. Tests whose names already describe intent need no explanatory comment.
  Reserve longer explanation for genuinely complex or non-obvious logic (e.g. a
  security check whose threat model isn't apparent), and keep even that as tight
  as it can be. Over-commenting is noise that ages badly and obscures the code it
  wraps.
- **Imports at top of file.** Valid exceptions: circular imports, lazy loading for
  worker isolation, `TYPE_CHECKING` blocks.
- **Name functions and methods with action verbs:** `get_`, `extract_`, `find_`,
  `compute_`, `build_`, etc. Avoid noun-only names like `_serialize_keys` or
  `_base_names` — they read as attributes, not callables. Predicates (`is_`,
  `has_`) are the one exception.
- **Avoid globals where possible,** favouring constants in local scope. The
  exception is a module-scope constant used in multiple places. If a value is
  configurable, it belongs in config.
- Absolute imports (`from src.retrieval.indexer import ...`).

## Testing Standards

- **Target exactly 100% coverage of what the PR changes — no more, no less.**
  Every changed or added behaviour must have a test; every test must fail without
  the PR's change. Do not add tests for pre-existing logic, and do not test
  standard-library or third-party functions. The exception is deliberate
  behaviour or integration tests, which may cross those boundaries by design.
- Tests live in `tests/` and test logic, not HTTP/framework plumbing.
- Use pytest patterns, not `unittest.TestCase`.
- Use `spec`/`autospec` when mocking.
- Prefer `@mock.patch` decorators over `with mock.patch(...)` context managers.
- Use `@pytest.mark.parametrize` for multiple similar inputs — consolidate tests
  that only differ in input/expected values into a single parametrized test.
- Tests that need a database run against local Postgres and skip themselves when
  it isn't running (see `tests/test_pg_indexer.py`); never point them at the
  real `DATABASE_URL`.
- Do not assert on raw log text.
