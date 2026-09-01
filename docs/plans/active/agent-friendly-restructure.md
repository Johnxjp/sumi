# Restructure docs and tooling so agents can navigate sumi-backend

## Purpose

Make the repo easier for coding agents to work in. Today the guidance is spread
over five files that partly repeat and partly contradict each other, one of them
is a pre-implementation plan that reads as current state, the design docs are
gitignored, and `ruff check .` is red. This restructure fixes those. It is a
docs + tooling change: **no behaviour changes** to any Python module except
the small path consolidation in step 9.

## Context you need before starting

- Git root is `/Users/johnlingi/programming/sumi`. The backend is the
  `sumi-backend/` subdirectory; all `uv` commands run from there.
- `sumi-backend/CLAUDE.md` contains only `@AGENTS.md`; `AGENTS.md` is the file
  agents load on every session. Its "Coding Standards", "Testing Standards"
  and "Explaining Work" sections are rules — follow them for this task too.
- `AGENTS.md` has an **uncommitted** edit on the current branch
  (`retrieval-eval`) that adds the "Explaining Work" section. Keep that
  section; do not discard the working-tree change.
- `../.gitignore` (the root one) ignores `data/`, `docs/` and `secrets/` at
  any depth, and contains a no-op absolute-path line
  `/Users/johnlingi/programming/sumi`.
- Existing design docs, not tracked by git because of the ignore rule:
  `../docs/mcp-integration.md` (Gmail/MCP design and history) and
  `../docs/sumi-evaluation.md` (eval datasets, annotation, open questions).
- `RETRIEVAL_PLAN.md` was the plan for commits `26a11fa`..`d5296ff`. It has
  been executed. Its opening claim "there is no evaluation code anywhere" is
  now false.
- Baseline before you start: `uv run pytest` → 187 passed in ~4s (Postgres
  running locally, so the `postgres`-marked tests run rather than skip).
  `uv run ruff check .` → 2 errors (`evals/note_length.ipynb` RUF013,
  `src/tools/core.py:12` BLE001). `pyproject.toml` has no `[tool.ruff]`
  section. ruff is 0.16.3.

## Decisions already made (do not re-open)

- New docs live in `docs/`.
- `AGENTS.md` moves into root so does claude.md. Agent.md is main doc. It keeps everything an agent must know on **every** task (commands,
  traps, invariants, standards) and becomes a **map** to `docs/` for
  everything else. Target: under 100 lines.
- Every topic has exactly **one** home. Other files link to it; they do not
  summarise it. The one exception: a command may appear both in the
  `AGENTS.md` commands table and in the doc that explains it.
- Docs describe **current state**, in plain language (see the "Explaining
  Work" rules in `AGENTS.md`). No "we will", no "phase 1". History goes under
  a heading that says it is history.

## Steps

1. remove docs from gitignore
2. merge retrieval plans and delete obsolete ones in docs
3. Rewrite `AGENTS.md`. 
- Compress script commands. you can put a separate agents.md in the scripts folder that gives overview
- Split testing into separate document in docs

Target outline (under 100 lines):

```
# AGENTS.md
<one paragraph: what sumi is, where the notes and eval data live>

## Commands
<high level commands. add `docs/` pointers where a command has a doc — e.g. "see docs/evals.md">

## Map (code folder structure. don't need all files just at the directory / module level)
<one line per package, each with the doc to read:>
- `main.py`, `src/agent.py`, `src/tools/` — terminal REPL with filesystem +
  Gmail tools; does not use the retrieval stack. Gmail: docs/gmail-mcp.md
- `src/retrieval/` — chunk → embed → pgvector; hybrid search. docs/retrieval.md
- `src/annotation/` + `static/` — relevance labelling UI. docs/annotation.md
- `evals/` — query generation and the retrieval eval harness. docs/evals.md
- `scripts/` — ingest, build_fts, search, smoke scripts
- `tests/` — pytest; `postgres` marker for DB tests

## Traps and invariants
<keep, tightened to one bullet each:>
- src/config.py extra="forbid": every .env var needs a field or all imports of
  app_config fail
- scripts run from repo root with -m (absolute src. imports)
- chunk ids are "{source}#{chunk_index}" and identical across every table;
  fusion dedup and judgment joins depend on it
- `chunks` (gemini) table is stale — never use it
- build_arm_indexer refuses to pair an embedder with another embedder's table
- the train/val split is never regenerated without --force; doing so makes
  every recorded run incomparable
- DB tests use the test_db_url fixture, never the real DATABASE_URL

## Configuration
<the three config objects, two lines each — no more>

## Explaining Work        (verbatim from the current working tree)
## Coding Standards       (verbatim)
## Testing Standards      (verbatim)
```

Remove all architecture prose that a `docs/` file now owns. Fix the stale
retriever-type list (it belongs in `docs/annotation.md` anyway).

Check: `wc -l AGENTS.md` < 100; every `docs/*.md` file is linked from it;
the three standards sections are byte-identical to before; no paragraph in
`AGENTS.md` also appears in a `docs/` file.

### 5. Trim both READMEs to human quick-starts

`sumi-backend/README.md`: what it is, `uv sync`, `uv run main.py`, the
search one-liner, then a "Docs" list linking `AGENTS.md` and the four
`docs/` files. Delete the "Annotation app" section (now `docs/annotation.md`).

`../README.md`: keep the first paragraph; replace the whole "Gmail tools"
section with two sentences and a link to `sumi-backend/docs/gmail-mcp.md`.
Point "architecture and commands" at `sumi-backend/AGENTS.md`.

Check: `grep -n "gmail.readonly" ../README.md README.md` prints nothing.

### 6. Make `ruff check .` green and declare the config in the repo

In `pyproject.toml` add:

```toml
[tool.ruff]
extend-exclude = ["*.ipynb"]
```

In `src/tools/core.py`, the `except Exception` at line 12 is deliberate: the
dispatcher turns any tool failure into a string returned to the model
instead of crashing the REPL. Keep it and suppress with a reason, e.g.
`except Exception as e:  # noqa: BLE001 - tool errors go back to the model as text`.
Do not loosen any rule in `[tool.ruff.lint]`.

Check: `uv run ruff check .` → "All checks passed!";
`uv run ruff format --check .` → no files would be reformatted;
`uv run pytest` → 187 passed.

### 7. Rename the misnamed smoke script

`git mv scripts/test_breadbowl.py scripts/breadbowl_smoke.py` (matches
`scripts/gmail_smoke.py`; a `test_*.py` name outside `tests/` reads as a
test). Grep the whole repo — `*.md`, `*.py`, `*.toml`, `*.sh` — for
`test_breadbowl` and update any reference.

Check: `uv run python -m scripts.breadbowl_smoke --help` runs.

### 8. Add a one-line module docstring to every module that lacks one

Line 1, `"""What this module is for."""`, in the style of
`src/retrieval/search_config.py` and `evals/retrieval/paths.py`. Say the
purpose, not a narration of the contents. Files:

```
evals/config.py            evals/utils.py             scripts/breadbowl_smoke.py
src/agent.py               src/annotation/app.py      src/annotation/config.py
src/annotation/models.py   src/annotation/pooling.py  src/annotation/retrievers.py
src/annotation/store.py    src/config.py              src/mcp_client.py
src/retrieval/chunker.py   src/retrieval/cleaner.py   src/retrieval/embedder.py
src/retrieval/indexer.py   src/tools/core.py          src/tools/file.py
src/tools/gmail.py         src/tools/mcp.py           src/tools/registry.py
```

Check: this prints nothing —
`for f in $(git ls-files 'src/*.py' 'evals/*.py' 'scripts/*.py' | grep -v __init__); do head -1 "$f" | grep -q '^"""' || echo "$f"; done`

### 9. One source of truth for data paths (optional, do last)

`evals/retrieval/paths.py` and `src/annotation/config.py` both compute
`REPO_ROOT` and the `../data` location. Create `src/paths.py` holding
`REPO_ROOT`, `DATA_DIR`, `ANNOTATIONS_PATH`; make the other two import from
it (`src/` must not import from `evals/`). No new tests: nothing behavioural
changes, and the existing tests exercise every path constant.

Check: `uv run pytest` → 187 passed; `grep -rn "parents\[2\]" src evals`
shows only `src/paths.py`.

### 10. Permission allowlist (default yes — see owner decisions)

Add to `sumi-backend/.claude/settings.json`, alongside the existing hook:

```json
"permissions": {
  "allow": [
    "Bash(uv run pytest*)",
    "Bash(uv run ruff*)",
    "Bash(git status*)",
    "Bash(git diff*)",
    "Bash(git log*)"
  ]
}
```

Check: the file is valid JSON (`jq . .claude/settings.json`).

## Definition of done

All of these, run from `sumi-backend/`:

1. `uv run ruff check .` → All checks passed. `uv run ruff format --check .` → clean.
2. `uv run pytest` → 187 passed (Postgres running; if it is not, start it —
   skipped DB tests do not count).
3. `git check-ignore -v docs/retrieval.md` → nothing.
4. `wc -l AGENTS.md` < 100 and it links every file in `docs/`.
5. `RETRIEVAL_PLAN.md` and `../docs/` are gone; `../README.md` and
   `README.md` contain no Gmail setup or annotation how-to.
6. Every command in `AGENTS.md` and `docs/` has been run (or `--help`ed).
7. Every file path, table name and config value in the docs was grepped
   and found in the code.
8. Read `AGENTS.md` then each `docs/` file once, cold, and fix any sentence
   that needs context the reader does not have yet.

## Commits

On the current branch, do not push. Two commits, messages written per the
"Explaining Work" rules (say what a reader unfamiliar with the project needs):

1. Docs restructure: steps 1–5.
2. Tooling: steps 6–10.
