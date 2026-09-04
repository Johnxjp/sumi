# Sync the corpus from Notion instead of a manual export

Status: designed and phases 1–3 built; not yet switched on. `ACTIVE_CONFIG`,
the search configuration that ships, still reads the tables built from the
hand-made export. Switching it needs a Notion integration token, the export
folder and a running Postgres, which only the owner's machine has.

The design is `docs/designs/notion-sync.md`. It is the single source of truth
for how the sync works and why; this note only tracks what is done.

## Phases

1. **Client, normaliser, oracle.** `src/notion/client.py`, `properties.py`,
   `markdown.py`, `scripts/check_export_fidelity.py`, the `notion_token`
   setting, `httpx` declared. No database change. **Done.**
2. **Sync.** Delete and metadata methods on both indexers, a real
   `PgFtsIndexer.index`, `SYNC_CONFIG`, `src/notion/mirror.py`,
   `src/notion/sync.py`, `scripts/sync.py`, the `data_dir` default, the
   search tool's `path` field, the staleness line at REPL start. **Done**, and
   a first full sync has run: 2,130 pages on 2026-09-04.
3. **Two corpora, kept apart.** The eval corpus is frozen and the labels stay
   on it; the synced corpus serves the agent. See §0 of the design for why.
   Built: generated-query scoring finds a note by page id in either corpus,
   `selftest --corpus` chooses between them, and `scripts/migrate_eval_ids.py`
   is deleted. **Left to do on the owner's machine:** grant the integration
   the pages it cannot see, re-sync, then set `ACTIVE_CONFIG = SYNC_CONFIG` so
   the agent reads the synced corpus.
4. **Cleanup.** Drop `chunks` (stale Gemini) and `chunks_qwen_title`
   (measured, unused). The export folder and the `chunks_qwen`,
   `chunks_bge_m3` and `chunks_fts` tables are **kept** — they are the frozen
   eval corpus. Not started.

## Done when

- `scripts.sync --full` indexes the connected workspace from empty tables;
  `scripts.sync` picks up a page edited a minute earlier and drops a page
  moved to trash, both within one run. **Done**, except that the integration
  cannot yet see every page: the first full sync found 2,130 of the export's
  2,329, missing all of Scratchpad and Knowledge Centre.
- Chunks carry title, path, created and last edited time, database properties
  and page URL. **Done.**
- `ACTIVE_CONFIG` reads the synced tables and the eval experiments read the
  frozen ones, `docs/architecture.md` says so, and this note moves to
  `docs/plans/completed/`.
