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
   setting, `httpx` declared. No database change. **Built.** Exit: the
   fidelity gate in the design's §9 passes — not yet run, it needs the token.
2. **Sync.** Delete and metadata methods on both indexers, a real
   `PgFtsIndexer.index`, `SYNC_CONFIG`, `src/notion/mirror.py`,
   `src/notion/sync.py`, `scripts/sync.py`, the `data_dir` default, the
   search tool's `path` field, the staleness line at REPL start. **Built.**
   Exit: checks 2–4 in §9 — not yet run.
3. **Eval migration and switch.** `evals/retrieval/qrels.py`,
   `selftest.py`, `runner.py`, `scripts/migrate_eval_ids.py`, the
   `rrf-3arm-k5-notion` experiment. **Code built.** Still to do on the
   owner's machine: run the migration, record the new baseline, set
   `ACTIVE_CONFIG = SYNC_CONFIG`, update `docs/designs/retrieval_overview.md`.
4. **Cleanup.** Delete the export folder and drop the old chunk tables
   (`chunks`, `chunks_qwen`, `chunks_bge_m3`, `chunks_fts`,
   `chunks_qwen_title`) once the switch has held. Not started.

## Done when

- `scripts.sync --full` indexes the connected workspace from empty tables;
  `scripts.sync` picks up a page edited a minute earlier and drops a page
  moved to trash, both within one run.
- Chunks carry title, path, created and last edited time, database properties
  and page URL.
- The normaliser's fidelity against the export passes its gate: at least 95%
  of unedited pages chunk identically, and every relevant note in the judged
  set chunks identically or has a written-down reason.
- `evals.retrieval.selftest --corpus notion` passes on the migrated ids, and
  `rrf-3arm-k5-notion` is recorded and compared with `rrf-3arm-k5`.
- `ACTIVE_CONFIG` reads the synced tables, `docs/architecture.md` says so,
  and this note moves to `docs/plans/completed/`.
