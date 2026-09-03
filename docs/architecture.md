# Architecture

What the code in `sumi-backend/` is made of and how data moves through it.
Paths below are relative to `sumi-backend/`. For search quality — metrics,
datasets, why the shipped configuration was chosen — read
`docs/retrieval/retrieval_overview.md`; this page is the map of the parts.

## The parts

Five loosely coupled pieces share one Postgres database and one notes
directory (`data/notion-export-markdown` at the repo root, configurable as
`data_dir`).

**1. Agent CLI** — `main.py` → `src/agent.py` + `src/tools/`. A terminal REPL
running an OpenRouter tool-calling agent. By default the loop prints its
intermediate steps (model reasoning and each tool call); `uv run main.py
--quiet` hides them and shows only the final answer. Its filesystem tools
(`src/tools/file.py`, registered through `src/tools/registry.py`) read the
notes directory: read a file, list a directory, ripgrep search — all sandboxed
to `data_dir`. Its `search_notes` tool (`src/tools/search.py`, registered
explicitly by `main.py`) calls `src/retrieval/retrieve.py:retrieve()` at the
shipped configuration's `top_k` (10, from `src/retrieval/search_config.py`;
the model cannot change it) and returns each chunk as `{rank, chunk_id, source, title, text}`,
which `src/tools/core.py` serialises to JSON for the model. The tool
description says when to use it (questions, information found by similarity)
rather than `grep` (specific terms in a title or note), and how to phrase the
query: with the words the note itself would contain, dropping words that only
describe the request. The system prompt adds the conversation behaviour: work
out what the user actually wants before searching, split a multi-part request
into several searches, say how the request was interpreted, and call
`read_file` on a chunk's `source` for the whole note. Once a turn ends, each `search_notes` result in
the history is replaced by a stub (the query, then every chunk's rank, title
and source path), so ten chunks of text are not re-sent on every later call;
a tool opts in by passing a `summarise` function to `register_tool`, and only
`search_notes` does. There is no relevance cut-off: every eval number
is measured at an unthresholded top 10, and the fused score measures how many
arms agree, not relevance, so a cut-off would be a retrieval experiment.
Nothing measures the answers the agent produces.

At startup it also registers read-only Gmail tools over MCP. `src/mcp_client.py`
is a generic synchronous client for any streamable-HTTP MCP server;
`src/tools/mcp.py` discovers a server's tools, filters them against an
allowlist and registers them; `src/tools/gmail.py` applies that to a locally
run workspace-mcp server. If the server is not running the REPL runs with the
notes tools only. Detail and history: `docs/mcp-integration.md`.

**2. Retrieval pipeline** — `src/retrieval/`. Ingestion
(`scripts/ingest.py`) is `cleaner.clean_text` → `chunker.chunk_text`
(2,000-char max, 200 min, 50 overlap) → an `Embedder` → an `Indexer`. Query
time (`retrieve.py`) runs the arms declared in `search_config.ACTIVE_CONFIG`
concurrently — dense arms over pgvector, a lexical arm over Postgres
full-text search (`lexical.py`) — and merges them with reciprocal rank fusion
(`fusion.py`). `scripts/search.py` is the command-line front end.

**3. Annotation tool** — `src/annotation/` + `static/`. A FastAPI backend and
one vanilla-JS page for grading how relevant a chunk is to a query (0/1/2),
blind to which retriever returned it. Produces the human judgments the evals
score against. Detail: `docs/annotation.md`.

**4. Evals** — `evals/`. `generate_notes_sample.py` and `generate_queries.py`
build the synthetic query set with an LLM; `evals/retrieval/` is the harness
that runs a retrieval configuration over both query sets, records the run and
compares runs. Detail: `docs/retrieval/retrieval_overview.md`.

**5. Shared plumbing** — `src/config.py` (settings), `src/paths.py`
(filesystem layout: `REPO_ROOT`, `DATA_DIR`, `ANNOTATIONS_PATH` — the only
place these are computed).

## Storage

One table per embedding model, all created by `ensure_schema()` in
`src/retrieval/indexer.py`, plus the lexical table:

| table | contents | used by |
|---|---|---|
| `chunks_qwen` | Qwen3-Embedding-0.6B vectors (1024-dim) | `qwen` arm |
| `chunks_bge_m3` | BGE-M3 vectors (1024-dim) | `bge-m3` arm |
| `chunks_fts` | text + title as a `tsvector`, copied from `chunks_qwen` by `scripts/build_fts.py` | `fts` arm |
| `chunks_qwen_title` | Qwen vectors of title-prefixed chunks | measured, not used |
| `chunks` | Gemini vectors, older chunking | **stale — never use** |

Every table stores the same chunks under the same ids,
`"{source}#{chunk_index}"`. Re-running ingest upserts in place, fusion can
deduplicate across arms by id, and a human judgment recorded against an id
applies to that chunk in every table. This is the invariant most of the system
rests on; `build_arm_indexer` enforces its query-time half by refusing to pair
an embedder with a table built by a different embedder.

Each chunk carries one piece of metadata: the note title. Nothing else
(dates, tags, folder) is indexed — see `docs/retrieval/retrieval_improvements.md`.

## Embedders

`src/retrieval/embedder.py`: `GeminiEmbedder` (API, 768-dim, free-tier
rate-limit handling) and two local sentence-transformers models,
`QwenEmbedder` and `BgeM3Embedder`, sharing a `SentenceTransformerEmbedder`
base with lazy model loading. Every embedder takes `max_seq_length` (tokens)
and an `overflow_strategy` (`chunking-average` default, `truncate`,
`barbell`); over-length inputs are handled once in the `Embedder` base class.
`TitlePrefixEmbedder` wraps any of them to prepend the note title at embed
time while leaving the stored text — and therefore the ids — untouched.

## Configuration

Three objects, kept separate on purpose:

- `src/config.py` → `app_config` (pydantic-settings, reads `.env`): data dir,
  OpenRouter and Gemini keys, `DATABASE_URL`, BreadBowl credentials. It sets
  `extra="forbid"`, so **every variable in `.env` must have a field** — an
  unknown variable breaks every import of `app_config`.
- `evals/config.py` (pydantic-settings, reads `.env`): model, temperature and
  concurrency for query generation.
- Plain Python, no environment variables: `src/retrieval/search_config.py`
  (the arms and fusion settings; `ACTIVE_CONFIG` is what ships) and
  `src/annotation/config.py` (the retrievers the annotation UI pools).

`.env` and `secrets/` are gitignored.
