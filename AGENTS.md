# AGENTS.md

A map of the sumi repository for coding agents.

`docs/` is the system of record — a fact that is not in the repository does
not exist to an agent, so when you learn one, write it into the doc that owns
the topic rather than into this file or a chat message.

## What sumi is

A RAG system over a personal Notion export (~2,300 notes, ~6,000 chunks).

Today: a terminal agent with filesystem, note-search and read-only Gmail
tools, a hybrid retrieval stack over pgvector (two embedding models plus a
lexical index, fused), a blind relevance-labelling UI, and an evaluation
harness that picks the retrieval configuration. The agent's `search_notes`
tool calls the retrieval stack; the answers it produces are not measured yet.

## Repository outline

```
sumi/
├── AGENTS.md, CLAUDE.md    this map (CLAUDE.md only includes it)
├── .claude/settings.json   hook: ruff on every edited .py file
├── docs/                   system of record — index below
├── data/                   gitignored: notes export, annotations, eval runs, queue
└── sumi-backend/           all code. Python 3.12, uv. Run every uv command from here.
    ├── main.py             terminal REPL entry point
    ├── src/agent.py, src/tools/   OpenRouter tool-calling agent; file, search + Gmail (MCP) tools
    ├── src/mcp_client.py   generic client for any streamable-HTTP MCP server
    ├── src/retrieval/      clean → chunk → embed → pgvector; hybrid search + RRF fusion
    ├── src/annotation/     FastAPI backend of the labelling UI (page in static/)
    ├── src/config.py       app settings from .env · src/paths.py: REPO_ROOT, DATA_DIR
    ├── evals/              query generation; evals/retrieval/ is the eval harness
    ├── scripts/            ingest, build_fts, search, MCP smoke scripts
    └── tests/              pytest; `postgres` marker for tests needing a local DB
```

## Docs index

Documents and when to read them.

- `docs/architecture.md`: before changing code — the parts, data flow, tables, config objects.
- `docs/retrieval/retrieval_overview.md`: anything about search quality — current metrics, datasets, methodology, shipped config.
- `docs/retrieval/retrieval_improvements.md`: known weaknesses and measurement gaps; the retrieval tech-debt list.
- `docs/annotation.md`: how human relevance judgments are produced and stored.
- `docs/mcp-integration.md`: Gmail tools, the MCP client, adding another mail provider.
- `docs/testing.md`: what a change must cover, how to run tests, the Postgres fixture.
- `docs/coding-standards.md`: style rules, and how to explain work to the user.
- `docs/plans/active/`, `docs/plans/completed/`: execution plans; completed ones are history, not current state.
- `docs/todos/`: known gaps, one note per issue, with the evidence and a proposed fix. When the work ships, update the owning doc and move the note to `docs/todos/complete/`.

## Commands

Run from `sumi-backend/`. Scripts and eval modules use absolute `src.` imports,
so they only run with `-m` from there.

- Install, test, lint: `uv sync` · `uv run pytest` · `uv run ruff check . --fix && uv run ruff format .`
- Agent REPL: `uv run main.py` (Gmail tools need `./scripts/run_gmail_mcp.sh` running first)
- Ingest, then build the lexical index: `uv run python -m scripts.ingest --embedder qwen` (and `bge-m3`), then `uv run python -m scripts.build_fts`
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
