# Architecture

What the code in `sumi-backend/` is made of and how data moves through it.
Paths below are relative to `sumi-backend/`. For search quality — metrics,
datasets, why the shipped configuration was chosen — read
`docs/retrieval/retrieval_overview.md`; this page is the map of the parts.

## The parts

Six loosely coupled pieces share one Postgres database and one notes
directory (`data_dir` at the repo root). Which directory that is, is
mid-migration: `data_dir` now defaults to `data/notion-mirror`, the folder the
Notion sync writes, while the hand-made export in `data/notion-export-markdown`
is what the tables the shipped search reads were built from. Until the first
sync has run and been checked, point `DATA_DIR` at the export.

**1. Agent** — `src/agent.py` + `src/tools/`, reached through two front ends.
`Agent.stream()` runs the OpenRouter tool-calling loop with streaming on and
yields events as it goes: a `TextDelta` for each piece of assistant text and a
`ToolCall` just before a tool runs. If the model or a tool fails, the whole
exchange is dropped from the history so the next query starts clean.
`src/bootstrap.py` holds the system prompt and registers every tool, so both
front ends behave the same. The terminal REPL (`main.py`) calls `Agent.run()`,
which joins the final turn's text; by default it prints only the answer, and
`uv run main.py --verbose` also prints the model's reasoning and each tool
call; the web chat server always prints them. The web chat (`src/chat/` + `sumi-frontend/`; detail:
`docs/designs/chat-ui.md`) forwards the events to the browser as server-sent
events. The agent's filesystem tools
(`src/tools/file.py`, registered through `src/tools/registry.py`) read the
notes directory: read a file, list a directory, ripgrep search — all sandboxed
to `data_dir`. Its `search_notes` tool (`src/tools/search.py`, registered
by `src/bootstrap.py`) calls `src/retrieval/retrieve.py:retrieve()` at the
shipped configuration's `top_k` (10, from `src/retrieval/search_config.py`;
the model cannot change it) and returns each chunk as
`{rank, chunk_id, page_id, path, title, text}`,
which `src/tools/core.py` serialises to JSON for the model. `page_id` and
`path` are separate fields because a chunk's `source` column holds a Notion
page id once notes come from the sync, and a page id is not something
`read_file` can open; `path` is the note's file, read from chunk metadata. The tool
description says when to use it (questions, information found by similarity)
rather than `grep` (specific terms in a title or note), and how to phrase the
query: with the words the note itself would contain, dropping words that only
describe the request. The system prompt adds the conversation behaviour: work
out what the user actually wants before searching, split a multi-part request
into several searches, say how the request was interpreted, and call
`read_file` on a chunk's `path` for the whole note. Once a turn ends, each `search_notes` result in
the history is replaced by a stub (the query, then every chunk's rank, title
and path), so ten chunks of text are not re-sent on every later call;
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

**2. Retrieval pipeline** — `src/retrieval/`. Ingestion is
`cleaner.clean_text` → `chunker.chunk_text` (2,000-char max, 200 min, 50
overlap) → an `Embedder` → an `Indexer`. Two things feed it:
`scripts/ingest.py` for a plain folder of files (`data/mem-export`), and the
Notion sync below for the notes themselves. Query time (`retrieve.py`) runs
the arms declared in `search_config.ACTIVE_CONFIG` concurrently — dense arms
over pgvector, a lexical arm over Postgres full-text search (`lexical.py`) —
and merges them with reciprocal rank fusion (`fusion.py`).
`scripts/search.py` is the command-line front end.

**3. Notion sync** — `src/notion/`, run by `scripts/sync.py`. **Built, not yet
switched on**: it writes its own tables, and `ACTIVE_CONFIG` still reads the
ones built from the hand-made export. It lists every page the integration can
see through Notion's REST API (`client.py`), fetches each new or edited page
as markdown in one request, rewrites that markdown into the shape the export
used (`markdown.py` and `properties.py`, the normaliser), re-indexes its
chunks in every table of `search_config.SYNC_CONFIG`, and regenerates the
notes folder on disk from the database at the end of every run (`mirror.py`).
`sync.py` is the job and its state tables. Chunks are keyed by Notion page id
rather than by file path, so a rename or a move no longer orphans them, and
each one carries the note's title, its file in the mirror, created and last
edited times, database properties and page URL.
`scripts/check_export_fidelity.py` measures how far the normaliser's output
has drifted from the export; it is a diagnostic, not a gate. Detail:
`docs/designs/notion-sync.md`; what is left to do:
`docs/plans/active/notion-sync.md`.

**There are two corpora, on purpose.** The hand-made export and the tables
built from it are frozen: they are what the 171 human judgments were made on,
so eval runs stay comparable with each other for as long as they use it. The
synced tables and `data/notion-mirror` are live and change whenever a note
does. Judgments are never carried between the two — a judgment is joined to a
chunk by a hash of the chunk's text, and text that changes loses its label.
Eval experiments name the frozen tables; the agent reads the live ones.

**Usage log** — `src/usage.py`. Every `search_notes` call appends one line of
JSON to `data/usage/searches.jsonl`: the question the user typed, the query the
agent rewrote it into (the two differ, because the agent is told to search with
the words a note would contain), the corpus version, the retrieval
configuration's name, and the ranked chunk ids that came back. Nothing scores
it. It is kept so that real questions can be labelled into an eval set later,
instead of inventing queries by hand. The user's wording reaches the tool
through a context variable the agent sets for the length of a turn.

**4. Annotation tool** — `src/annotation/` + `static/`. A FastAPI backend and
one vanilla-JS page for grading how relevant a chunk is to a query (0/1/2),
blind to which retriever returned it. Produces the human judgments the evals
score against. Detail: `docs/annotation.md`.

**5. Evals** — `evals/`. `generate_notes_sample.py` and `generate_queries.py`
build the synthetic query set with an LLM; `evals/retrieval/` is the harness
that runs a retrieval configuration over both query sets, records the run and
compares runs. Detail: `docs/retrieval/retrieval_overview.md`.

**6. Shared plumbing** — `src/config.py` (settings), `src/paths.py`
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
| `chunks_qwen_notion` | the same, filled by the Notion sync | `SYNC_CONFIG`, not shipped yet |
| `chunks_bge_m3_notion` | the same, filled by the Notion sync | `SYNC_CONFIG`, not shipped yet |
| `chunks_fts_notion` | the same, filled by the Notion sync | `SYNC_CONFIG`, not shipped yet |
| `notion_objects` | one row per Notion page, data source and database: title, parent, path, times, properties, and the page's normalised text | the sync; the mirror is written from it |
| `notion_sync_runs` | one row per sync run: mode, times, status, counts | the sync's watermark, the REPL's staleness line |

Every table stores the same chunks under the same ids, and the id scheme
depends on which set of tables. The export-built tables use
`"{file path}#{chunk_index}"`; the `_notion` tables use
`"{32-hex Notion page id}#{chunk_index}"`, which survives a note being renamed
or moved. **The two schemes must never meet in one table** — nothing but the
sync writes the `_notion` tables, and `scripts/ingest.py` must never be
pointed at them — because fusion deduplicates by id and would otherwise count
one chunk twice. Within a set, re-running upserts in place, fusion can
deduplicate across arms by id, and a human judgment recorded against an id
applies to that chunk in every table. `build_arm_indexer` enforces the
query-time half by refusing to pair an embedder with a table built by a
different embedder; the `_notion` names keep the prefixes it checks.

Chunks in the export-built tables carry one piece of metadata, the note title.
Chunks the sync writes carry the title, the note's `path` inside the mirror
(what `read_file` takes), `created_time`, `last_edited_time`, the page `url`
and its database `properties`. Nothing reads the new keys yet — using them for
ranking is a separate experiment, see
`docs/retrieval/retrieval_improvements.md`.

`SYNC_CONFIG` in `src/retrieval/search_config.py` declares the three `_notion`
arms; `ACTIVE_CONFIG`, what ships, still declares the export-built ones.
Switching is one line, and waits on the fidelity check in
`docs/plans/active/notion-sync.md`.

## Embedders

`src/retrieval/embedder.py`: `GeminiEmbedder` (API, 768-dim, free-tier
rate-limit handling) and two local sentence-transformers models,
`QwenEmbedder` and `BgeM3Embedder`, sharing a `SentenceTransformerEmbedder`
base that loads its model on first use, or up front through
`HybridRetriever.load_models()` (the web chat server does this at startup). Every embedder takes `max_seq_length` (tokens)
and an `overflow_strategy` (`chunking-average` default, `truncate`,
`barbell`); over-length inputs are handled once in the `Embedder` base class.
`TitlePrefixEmbedder` wraps any of them to prepend the note title at embed
time while leaving the stored text — and therefore the ids — untouched.

## Configuration

Three objects, kept separate on purpose:

- `src/config.py` → `app_config` (pydantic-settings, reads `.env`): data dir,
  OpenRouter and Gemini keys, `DATABASE_URL`, `NOTION_TOKEN` (the read-only
  Notion integration secret the sync needs; empty means the sync refuses to
  run), BreadBowl credentials. It sets `extra="forbid"`, so **every variable
  in `.env` must have a field** — an unknown variable breaks every import of
  `app_config`.
- `evals/config.py` (pydantic-settings, reads `.env`): model, temperature and
  concurrency for query generation.
- Plain Python, no environment variables: `src/retrieval/search_config.py`
  (the arms and fusion settings; `ACTIVE_CONFIG` is what ships, `SYNC_CONFIG`
  is what the Notion sync fills) and `src/annotation/config.py` (the
  retrievers the annotation UI pools).

`.env` and `secrets/` are gitignored.
