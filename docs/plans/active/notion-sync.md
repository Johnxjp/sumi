# Sync the corpus from Notion instead of a manual export

Status: open, design not yet drafted. Raised 2026-09-03 out of
`docs/notion-mcp-investigation.md`, which measured Notion MCP's own search
against the local retrieval stack and concluded: keep retrieval, feed it from
Notion. This note collects the facts and decisions gathered so far so the
design can be written without re-deriving them.

## Problem

Retrieval reads the Postgres chunk tables; the tables are filled by
`scripts.ingest` from a folder of markdown files that someone exported from
Notion by hand. Consequences today:

- **Stale.** The export's newest note is dated 2026-08-09. Notion holds pages
  edited on 2026-09-03, including *Daily Check In @August 20, 2026*, the
  answer to a judged query that scores as unanswerable
  (`retrieval_improvements.md`, A5).
- **Manual.** Refreshing means export, unzip, `scripts.ingest` twice (one per
  embedder), `scripts.build_fts`. Nobody does this on a schedule.
- **Lossy.** The export flattens a page to a filename. Path, created time,
  last edited time and database properties (Journal `Tags`, Task Management
  `Category`) are gone, which is why dates and metadata are blind spots (B1,
  B2). Untitled pages become a 32-character hash (B2). The export produced
  twin folders *Document Hub* and *Document Hub (1)* that split credit (A6).

The Notion REST API is free on every plan, rate-limited to about three
requests per second per integration plus a per-workspace ceiling scaled to
the plan. That is enough to keep 2,300 pages current from a laptop.

## Proposed design

### Authentication

An **internal integration** with read-content permission only, created by the
workspace owner in Notion's integration settings. Its secret goes in `.env`
as a new variable with a matching field in `src/config.py` (`extra="forbid"`
means an unmatched variable breaks every import). No OAuth: a background job
must not depend on a token that expires every eight hours, which is what the
hosted MCP server issues. MCP stays for the agent's live tools.

The integration sees only pages it is connected to. The owner connects it to
each top-level page (page menu, Connections); children inherit. There is no
whole-workspace switch, and a new top-level page needs connecting by hand.

### Discovery: list, do not traverse

`POST /v1/search` with an empty query lists every page and database row the
integration can see, 100 per request with a cursor, each with id, title,
parent, archived and trash flags, and `last_edited_time`. 2,300 pages is about
24 requests. It matches titles only when given a query; with none it is an
enumeration.

The sync keeps its own `pages` table: page id, title, parent id, path,
`last_edited_time`, indexed-at. Each run diffs the listing against it:

- **New**: id not in the table.
- **Changed**: `last_edited_time` newer than stored. Block edits bump the
  page's timestamp, so page-level comparison is enough.
- **Gone**: id in the table but absent from the listing, or now archived or
  trashed. Delete its chunks from every retrieval table.

Only new and changed pages have content fetched.

### Newest-first incremental runs

The search endpoint sorts by `last_edited_time` descending. An incremental run
walks the listing newest-first and stops at the first page older than the
last sync time, so a quiet day costs one request, and the freshest pages are
re-indexed first. If a run is interrupted, what got in is the newest content.
The same order makes the first sync useful within minutes: recent months are
searchable while old material fills in behind.

Two corrections that make this safe:

- **Overlap.** Notion rounds `last_edited_time` to the minute and its search
  index lags edits slightly. Stop a few minutes past the last sync time, and
  let the id diff skip pages already current.
- **Deletions need the full listing.** Stopping early never sees pages that
  vanished. Run the full 24-request listing on a slower cadence (nightly) to
  remove pages no longer returned.

Search sorts only by last edited time; "newest created" is a client-side sort
over the listing and in practice the same order.

### Tree and metadata from parent pointers

Every listed page names its parent: a page, a data source, or the workspace.
Following pointers upward gives the path (*Life OS / Career / Job Hunt
2025-2026*) without any traversal. Database rows arrive as pages whose parent
is a data source; their properties come with the listing. Store per chunk:
title, path, created time, last edited time, database properties. This is the
data B1 and B2 were waiting for.

### Content: blocks to markdown

For a changed page, `GET /v1/blocks/{id}/children`, 100 blocks per request,
recursing into blocks that report children (toggles, columns, nested lists).
A `child_page` block only names another page; do not descend, the listing
already covers it. Convert blocks to markdown in the shape the export
produced, then hand it to the existing clean, chunk, embed and upsert steps.
The block-to-markdown converter is the one genuinely new piece of code; the
alternative is the hosted MCP `fetch` tool, which returns markdown directly
but needs OAuth (see investigation doc).

Chunk ids become `{page_id}#{chunk_index}`. Delete chunk ids beyond the
page's new chunk count so a page that shrank leaves no orphans.

### Skip what did not change

Store a hash of each chunk's text. When a page changes, re-chunk it and embed
only chunks whose hash differs. Most edits touch one paragraph, and the two
local embedding models are the slow part of ingest, not the API.

### Rate limit

A token bucket at three requests per second, modest concurrency for block
fetches, back off on HTTP 429 using the `Retry-After` header.

### When it runs

1. On demand: `uv run python -m scripts.sync` (incremental) and `--full`.
2. On a schedule: cron or launchd every fifteen minutes, nightly `--full`.
   Same poller shape the mail-trigger ambition needs.
3. On REPL start: read the newest indexed-at from `pages`, print how stale
   the index is, optionally run an incremental sync first.

Notion webhooks push page events but need a public HTTPS endpoint; not for a
laptop CLI. Per-database queries (`POST /v1/data_sources/{id}/query` with a
`last_edited_time` filter) could refresh one database more often than the
rest if ever needed.

### First-time user

1. Create the read-only internal integration; copy the secret into `.env`.
2. Connect it to every top-level page to be indexed.
3. Start Postgres; run `scripts.sync --full`. API work takes minutes; the
   embedding pass is the same cost as today's ingest and the long pole.
4. Try `scripts.search` on a query with a known answer. The eval numbers do
   not transfer: judgments and generated queries are for this workspace only.
   A new user's retrieval quality is unmeasured until they label queries.
5. Schedule the incremental run.

## Decisions still open

- **Chunk id migration.** Judgments join on `"{source}#{chunk_index}"`.
  Either keep `source` as the export-style path or remap
  `data/annotations.json` once through the filename hash (which is the page
  id: every judged and generated note mapped in the investigation). Chunk
  boundaries move where text changed, so some chunk-level labels will not
  survive either way; `evals.retrieval.selftest` must pass before new numbers
  are trusted, and the train/val split must not be regenerated.
- **Filesystem tools.** `read_file` and `grep` read `data_dir`. Simplest: the
  sync also writes each page's markdown to disk under the same layout, so the
  export folder becomes a sync output and those tools do not change.
- **Converter scope.** Which block types to render (tables, callouts, toggles,
  equations, embeds) and what to do with file URLs, which expire.
- **Duplicates.** Whether to dedupe identical chunk text across pages at
  ingest, now that the twin-folder problem disappears but template notes
  remain.
- **Where the code lives.** `scripts/sync.py` plus `src/retrieval/notion.py`
  for the client and converter is the obvious split; not decided.

## Done when

- `scripts.sync --full` indexes the connected workspace from an empty
  database; `scripts.sync` picks up a page edited a minute earlier and drops
  a page moved to trash, both within one run.
- Chunks carry path, created and last edited time, and database properties.
- `evals.retrieval.selftest` passes on the migrated ids; the shipped
  configuration's eval numbers are re-recorded and compared.
- `docs/architecture.md` describes ingestion from Notion, the export folder
  is documented as a sync output or removed, and this note moves to
  `docs/todos/complete/`.
