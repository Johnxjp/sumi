# AGENTS.md

A map of the sumi repository for coding agents.

`docs/` is the system of record — a fact that is not in the repository does
not exist to an agent, so when you learn one, write it into the doc that owns
the topic rather than into this file or a chat message.

## What sumi is

A RAG system over a personal Notion export (~2,300 notes, ~6,000 chunks).

Today: an agent with filesystem, note-search and read-only Gmail tools,
used from a terminal REPL or a web chat page that streams its replies; a
hybrid retrieval stack over pgvector (two embedding models plus a lexical
index, fused); a blind relevance-labelling UI; and an evaluation harness
that picks the retrieval configuration. The agent's `search_notes` tool
calls the retrieval stack; the answers it produces are not measured yet.
A job that syncs the notes straight from Notion, replacing the hand-made
export, is built but not switched on: `docs/plans/active/notion-sync.md`.

## Repository outline

```
sumi/
├── AGENTS.md, CLAUDE.md    this map (CLAUDE.md only includes it)
├── .claude/settings.json   hook: ruff on every edited .py file
├── docs/                   system of record — index below
├── data/                   gitignored: notes export, annotations, eval runs, queue
├── sumi-frontend/          web chat page. Next.js + TypeScript, pnpm. Run pnpm commands from here.
└── sumi-backend/           all Python code. Python 3.12, uv. Run every uv command from here.
    ├── main.py             terminal REPL entry point
    ├── src/bootstrap.py    system prompt + tool registration, shared by the REPL and the web chat
    ├── src/agent.py, src/tools/   OpenRouter tool-calling agent (an event stream); file, search + Gmail (MCP) tools
    ├── src/chat/           FastAPI backend of the web chat: streams agent events as server-sent events
    ├── src/mcp_client.py   generic client for any streamable-HTTP MCP server
    ├── src/notion/         the sync: Notion REST client, markdown normaliser, mirror folder, the job itself
    ├── src/retrieval/      clean → chunk → embed → pgvector; hybrid search + RRF fusion
    ├── src/annotation/     FastAPI backend of the labelling UI (page in static/)
    ├── src/config.py       app settings from .env · src/paths.py: REPO_ROOT, DATA_DIR
    ├── evals/              query generation; evals/retrieval/ is the eval harness
    ├── scripts/            sync, ingest, build_fts, search, export-fidelity, eval-id migration, MCP smoke scripts
    └── tests/              pytest; `postgres` marker for tests needing a local DB
```

## Docs index

Documents and when to read them.

- `docs/active`: when checking approved plans that can be executed or have been implemented
- `docs/research`: locating investigations or experimental findings
- `docs/architecture.md`: before changing code — the parts, data flow, tables, config objects.
- `docs/design`: understand why certain decisions were made for components and how implemented
- `docs/testing.md`: what a change must cover, how to run tests, the Postgres fixture.
- `docs/coding-standards.md`: style rules, and how to explain work to the user.

## Commands

Run from `sumi-backend/`. Scripts and eval modules use absolute `src.` imports,
so they only run with `-m` from there.

- Install, test, lint: `uv sync` · `uv run pytest` · `uv run ruff check . --fix && uv run ruff format .`
- Agent REPL: `uv run main.py` (Gmail tools need `./scripts/run_gmail_mcp.sh` running first)
- Web chat: `uv run uvicorn src.chat.app:app --port 8766`, then from `sumi-frontend/`: `pnpm dev` (→ http://localhost:3000). Frontend checks: `pnpm test` · `pnpm lint` · `pnpm build`. Detail: `docs/designs/chat-ui.md`
- Sync the notes from Notion (built, not switched on yet — see `docs/plans/active/notion-sync.md`): `uv run python -m scripts.sync` · `--full` · `--dry-run` · `--limit 20` · `--mirror-only`. Needs `NOTION_TOKEN`. Detail: `docs/designs/notion-sync.md`
- Ingest a folder that is not a Notion workspace (`data/mem-export`), then build the lexical index: `uv run python -m scripts.ingest --embedder qwen` (and `bge-m3`), then `uv run python -m scripts.build_fts`
- Search: `uv run python -m scripts.search "your query"`
- Retrieval evals: `uv run python -m evals.retrieval.selftest` · `run <experiment>` · `compare` · `diagnose <run_id>`
- Annotation UI: `uv run uvicorn src.annotation.app:app --reload --port 8765`
- Generate eval queries: `uv run python -m evals.generate_notes_sample`, then `uv run python -m evals.generate_queries`

## Invariants — these break silently

- `src/config.py` sets `extra="forbid"`: every variable in `.env` needs a
  field there, or every import of `app_config` fails at import time.
- Chunk ids are `"{source}#{chunk_index}"` and identical in every table. Fusion
  deduplicates on them and eval judgments join on them; `build_arm_indexer`
  refuses an embedder paired with another embedder's table for the same reason.
  Two id schemes exist and must never meet in one table: the export-built
  tables key on the file path, the `_notion` tables on the Notion page id.
  Only `scripts/sync.py` writes the `_notion` tables; never point
  `scripts/ingest.py` at them.
- The `chunks` table (Gemini, older chunking) is stale. Never read from it.
- Never regenerate the train/val split (`make_split --force`): every recorded
  eval run becomes incomparable. Eval numbers are floors — an unlabelled result
  scores as irrelevant.
- Database tests use the `test_db_url` fixture, never the real `DATABASE_URL`.
- `src/paths.py` is the only place `REPO_ROOT` and `DATA_DIR` are computed.

## Working rules

- Explain plainly: define a term the first time you use it and assume no
  knowledge of project history — in replies, commit messages and PR bodies.
  Full rule: `docs/coding-standards.md`.
- Format and lint each Python file right after editing it (the hook does this
  for Edit/Write). Standards: `docs/coding-standards.md`.
- Every change is tested; done means `uv run pytest` and `uv run ruff check .`
  pass. Standards: `docs/testing.md`.
- Keep docs true. If a change makes a sentence in `docs/` false, fix it in the
  same change. New knowledge goes in the doc that owns the topic; this file
  only points. A finished plan moves to `docs/plans/completed/`, a finished
  todo to `docs/todos/complete/`.
