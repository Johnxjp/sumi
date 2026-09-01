# Coding standards

Rules for every Python change in `sumi-backend/`. `AGENTS.md` points here; this
is the only copy. Run ruff on each file right after editing it — the
PostToolUse hook in `.claude/settings.json` does this for Edit/Write calls,
but edits made any other way (a heredoc, a script) must run it by hand.

## Style

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

## Explaining work

Applies to replies, commit messages and PR descriptions.

- **Do not assume the reader knows the project's jargon or history.** The
  first time a term appears ("the join", "the pool", "baseline", "coverage"),
  say in plain words what it is. Say what a number means, not just what it is.
- **Use simple language.** Short sentences, concrete examples over abstract
  summaries. If a sentence needs prior context to make sense, give the context.

