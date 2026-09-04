# AGENTS.md

Guidelines for agents working in the Sumi codebase.
Sumi is an agent assisting with search and retrieval over personal notes.

## Repository Structure

```
sumi/
├── AGENTS.md, CLAUDE.md    Agent guidelines
├── docs/                   system of record — index below
├── data/                   notes export, annotations, eval runs, queue (gitignored)
├── sumi-frontend/          Web chat page. Next.js + TypeScript, pnpm. Run pnpm commands from here.
└── sumi-backend/           Backend server, agent code, retrieval and evals. Python 3.12, uv. Run every uv command from here.
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

## Commands

### Backend Specific
Run inside `sumi-backend`

```
uv sync              # install
uv run pytest        # test all
uv run ruff check . --fix && uv run ruff format .  # lint and format
uv run main.py       # agent repl
```

### Frontend Specific
```
pnpm install     # Install dependencies
pnpm test        # test
pnpm lint        # lint
pnpm build       # Build all packages
pnpm dev         # Dev server
```

### Web App
```
uv run uvicorn src.chat.app:app --port 8766 # start server. run in sumi-backend
pnpm dev # start app. (localhost:3000). run in sumi-frontend 
```

### Scripts
```
uv run python -m scripts.sync  # sync notes. Detail: @docs/designs/notion-sync.md
uv run python -m scripts.search "your query"  # search query
uv run python -m evals.retrieval.selftest  # retrieval evals. see script for commands

# Generate eval queries
1. uv run python -m evals.generate_notes_sample
2. uv run python -m evals.generate_queries

# Build the lexical index:
1. uv run python -m scripts.ingest --embedder <qwen / bge-m3> 
2. uv run python -m scripts.build_fts
```

### Annotation UI
```
uv run uvicorn src.annotation.app:app --reload --port 8765  # start app
```

## Docs index

Documents and when to read them.

- `docs/active`: when checking approved plans that can be executed or have been implemented
- `docs/research`: locating investigations or experimental findings
- `docs/architecture.md`: before changing code — the parts, data flow, tables, config objects.
- `docs/design`: understand why certain decisions were made for components and how implemented
- `docs/testing.md`: what a change must cover, how to run tests, the Postgres fixture.
- `docs/coding-standards.md`: style rules, and how to explain work to the user.


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

- Backend scripts and eval modules use absolute `src.`
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
