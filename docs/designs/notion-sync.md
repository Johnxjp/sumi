# Plan: write the Notion sync design document

## Context

Sumi's retrieval tables are filled from a folder of markdown files that the
owner exported from Notion by hand on 2026-08-09. The export is stale, manual
and lossy (`docs/plans/active/notion-sync.md`). On 2026-09-03 an investigation
(`docs/research/notion-mcp-investigation.md`) measured Notion's own search
against the local stack and concluded: keep retrieval, feed it from Notion.
The plan note collected facts but says "design not yet drafted".

This plan produces that design as `docs/designs/notion-sync.md`. The
document below is the full draft. On approval it is written to that path,
the active plan note is cut down to a pointer plus phases and done-when, and
the stale link in the investigation doc is fixed. No code changes in this
step; implementation is planned separately, phase by phase.

Decisions the owner made in this session (2026-09-04):

- Chunk ids become `{page_id}#{chunk_index}`.
- The sync writes a markdown mirror to disk; filesystem tools read it.
- Sync runs on demand (CLI now, a button in the web chat later); no
  scheduler yet.
- The document covers the sync only; agent-side Notion MCP tools are a
  follow-up.
- Build from scratch rather than update in place: the first sync fills
  fresh `_notion` tables (the export-built tables stay until the switch),
  and the mirror folder is regenerated from the database at the end of
  every run instead of being edited file by file.

Discovered during the session, and the reason the design differs from the
plan note: Notion's REST API has returned whole pages as markdown since
2026-02-26 (`GET /v1/pages/{id}/markdown`). The block-tree converter the
note called "the one genuinely new piece of code" is not needed; a small
normaliser is.

The working tree also holds uncommitted web-chat work (`src/bootstrap.py`,
`src/chat/`, `sumi-frontend/`, `docs/designs/chat-ui.md`). The design
refers to those files as they are on disk now, since the "UI" the owner
wants a sync button in is that web chat.

## Files to write or edit

1. `docs/designs/notion-sync.md` — new, the document below.
2. `docs/plans/active/notion-sync.md` — replace body with: status, link to
   the design, the four implementation phases, the done-when list.
3. `docs/research/notion-mcp-investigation.md` — fix the link
   `docs/todos/notion-sync.md` → `docs/plans/active/notion-sync.md`; add a
   pointer to the design; add one sentence under "Integration facts" that
   the REST API now returns markdown (the doc says the block API is the
   only REST path).
4. `AGENTS.md` docs index — no change; the "docs/design" line covers it.

## Verification

- Read each edited doc cold; every file path, table name and config value
  named in the design must either exist today or be marked as new.
- `grep -rn "docs/todos/notion-sync" docs/` prints nothing.

---

# The design document (to become `docs/designs/notion-sync.md`)

# Syncing the notes corpus from Notion

Design for replacing the hand-made Notion export with a job that pulls pages
from the Notion API into the existing retrieval tables and a markdown folder
on disk. Written 2026-09-04. Paths are relative to `sumi-backend/` unless
noted. Terms are defined the first time they appear.

## 1. Summary

Sumi keeps its own retrieval stack (two local embedding models plus a
lexical index over Postgres, fused) because it finds about twice as many
relevant notes as Notion's built-in search. What it lacks is freshness and
metadata, and both come from the source, not the retriever. So:

- A new **sync job** (`scripts/sync.py`, library code in `src/notion/`)
  lists every page the integration can see through Notion's REST API,
  fetches each new or edited page **as markdown in one request**
  (`GET /v1/pages/{id}/markdown`, available since 2026-02-26), normalises
  that markdown into the shape the old export used, re-indexes its chunks
  in the sync's own tables (which become the shipped configuration's once
  verified), and regenerates a **mirror folder** on disk from the database
  at the end of every run.
- Chunk ids change from `"{export path}#{index}"` to
  `"{page_id}#{index}"`, where `page_id` is the 32-character hex id Notion
  already puts in every export filename. Judgments and generated queries
  are migrated once; the eval self-test learns to tell "join broken" from
  "page edited since labelling".
- Each chunk gains metadata the export threw away: path, created and last
  edited time, database properties (Journal `Tags`, Task Management
  `Category`), and the page URL.
- Nothing about ranking changes. The retrieval trade-off measured on
  2026-09-03 stands: Notion is the source of truth for content; sumi is the
  retriever.

The only new rendering code is a **normaliser**: about fifteen line-based
rules that turn Notion's "enhanced markdown" into the export's markdown,
plus a page frame (title line and property lines). The one real risk is
that its output differs from the export's, which would orphan the human
labels that join on chunk text. The export folder itself is the oracle: the
normaliser is measured against it before anything is migrated.

## 2. Problem and goals

### The problem

Retrieval reads Postgres chunk tables filled by `scripts/ingest.py` from
`data/notion-export-markdown`, a folder someone exported from Notion by
hand. Three consequences:

- **Stale.** The export's newest note is dated 2026-08-09. Notion holds
  pages edited on 2026-09-03. One judged query ("what tasks did I put down
  on August 20, 2026") is unanswerable from the export and answerable from
  Notion.
- **Manual.** A refresh is: export, unzip, `scripts.ingest` twice (one per
  embedder), `scripts.build_fts`. Nobody does it on a schedule. Nothing
  deletes: a note removed or renamed in Notion leaves its old chunks in
  every table forever (there is no `DELETE` anywhere in `src/`, `scripts/`
  or `evals/`).
- **Lossy.** The export flattens a page to a filename. Path, created time,
  last edited time and database properties are gone; untitled pages become
  a 32-character hash; the export contains twin folders (*Document Hub* and
  *Document Hub (1)*) that split credit between duplicate notes.

### Goals

1. `scripts.sync --full` indexes the connected workspace from empty tables.
   `scripts.sync` (incremental) picks up a page edited a minute earlier and
   drops a page moved to trash, both within one run.
2. Every chunk carries title, path, created time, last edited time,
   database properties and page URL.
3. The agent's filesystem tools (`read_file`, `list_dir`, `grep`) keep
   working, over a folder the sync maintains.
4. The eval harness keeps its labels: `evals.retrieval.selftest` passes on
   migrated ids, and the shipped configuration's numbers are re-recorded.
5. The job is safe to interrupt and safe to re-run.

### Non-goals (each is a separate piece of work)

- Registering Notion's hosted MCP tools (`fetch`, `query-data-sources`)
  for the agent. That needs OAuth plumbing and its own allowlist; see §12.
- Using the new metadata in ranking (date filters, tag boosts). This design
  stores the data; experiments come after.
- Deduplicating identical chunk text across pages.
- Ingesting `data/mem-export` (a second notes app) — `scripts.ingest`
  stays for folders like it.
- Scheduling (launchd/cron), webhooks, and a sync button in the web chat
  (`src/chat/` + `sumi-frontend/`, in progress on this branch). The
  library entry point is designed so the button is a small follow-up.

## 3. The retrieval trade-off, in short

Measured 2026-09-03 on the same queries, at note level (a query counts as
answered if any chunk of a relevant note is in the top 10):

| | shipped `rrf-3arm-k5` | Notion workspace search |
|---|---|---|
| relevant notes found, 17 judged queries | 50 / 59 | 20 / 59 |
| judged queries with at least one hit | 17 / 17 | 11 / 17 |
| source note found, 20 generated queries | 19 / 20 | 12 / 20 |

Notion's search is keyword-based on this plan (semantic search needs a paid
Notion AI tier) and is crowded by a few large hub pages. It found nothing
the local stack missed. Replacing retrieval would halve quality and discard
every tuning lever and the whole eval harness.

What Notion offers that the local stack lacks — live content, dates, tags,
path, structured database queries — is all obtainable by syncing content
and metadata into the local stack. That is this design. The full analysis,
including what the hosted MCP server adds and what a replacement would
lose, is `docs/research/notion-mcp-investigation.md`.

## 4. Facts the design rests on

Verified against Notion's developer documentation on 2026-09-04 unless
marked "measured" (measured on this repository's data) or "observed"
(observed on real pages of this workspace, fetched through the Notion MCP
connector, whose page output uses the same enhanced-markdown renderer and
the same `truncated` / `unknown_block_ids` fields as the REST endpoint).

**Notion API**

- Authentication: an **internal integration** (created by the workspace
  owner in Notion's integration settings) has a secret that does not
  expire. Its capabilities are chosen at creation; "Read content" alone is
  enough. It sees only pages it has been given access to: either per page
  (page menu → Connections; children inherit) or in bulk from the
  integration's **Access** tab in Notion's developer portal.
- `POST /v1/search` with no query lists every page and data source the
  integration can see, 100 per request with a cursor. It sorts by
  `last_edited_time` ascending or descending (the only sort besides
  relevance). Results are full page objects: id, title property, parent,
  `created_time`, `last_edited_time`, `in_trash`, `url`, `properties`.
  Filter `{"property": "object", "value": "page"}` restricts to pages;
  `"data_source"` to data sources.
- `last_edited_time` and `created_time` are **rounded down to the minute**.
  Editing any block of a page bumps the page's `last_edited_time`.
- **`GET /v1/pages/{id}/markdown`** (Markdown Content API, launched
  2026-02-26, needs `Notion-Version: 2026-03-11` and the read-content
  capability) returns `{object: "page_markdown", id, markdown, truncated,
  unknown_block_ids}`: the whole page, nested blocks included, as
  **enhanced markdown** (Notion's own dialect: standard markdown plus
  HTML-style tags for what markdown lacks). `truncated` is set only past
  about 20,000 blocks; the largest note here has under 900 lines. Blocks the
  API cannot render appear as `<unknown url="…" alt="…"/>` (bookmarks,
  embeds, link previews, unsupported types). The documentation's example
  response begins with the page title as a `#` heading; whether that is the
  endpoint's frame or a heading block in the example page is settled by
  the oracle check (§9), and the frame code handles either.
- The endpoint's 403 error lists `workspace_credits_exhausted` among its
  causes. Notion's help pages tie credits to AI features; nothing says the
  read endpoint consumes them. Treated as a risk in §11 with a fallback.
- `GET /v1/blocks/{id}/children` (100 blocks per request, recursion for
  nested blocks) remains the fallback path if the markdown endpoint is ever
  metered or withdrawn. It is not used by this design.
- Rate limit: an average of **three requests per second per integration**,
  bursts allowed, plus a per-workspace ceiling scaled to the plan. Over the
  limit the API returns HTTP 429 (or 529 when overloaded) with a
  `Retry-After` header in seconds.
- Since API version `2025-09-03` a database can hold several **data
  sources** (tables); a database row's parent is a `data_source_id`, the
  data source's parent is a `database_id`, and the database's parent is a
  page or the workspace. Since `2026-03-11` `archived` is replaced by
  `in_trash`.
- The hosted MCP server (`mcp.notion.com`) issues OAuth tokens that last
  about eight hours and offers no static token. A background job cannot
  depend on a token that expires daily, which is why the sync uses the
  REST API and MCP stays for the agent's live tools.

**Enhanced markdown versus the export (observed on three pages: a Journal
row, a plain page with a quote and a child-page mention, and a Daily Check
In template)**

| | export (2026-08-09) | enhanced markdown |
|---|---|---|
| title | `# Title`, blank line | not in the page body (MCP wraps it in `<page>`; REST example shows a `#` heading — see above) |
| database properties | `Created: April 2, 2026 1:39 PM` / `Tags: Daily`, one line each, then a blank line | not in the body; the page object carries them as JSON (`"Created":"2026-04-02T12:39:07Z"`, `"Tags":["Daily"]`) |
| spacing between blocks | blank line after every block; list items contiguous | one newline; an empty paragraph is `<empty-block/>` |
| headings, bullets, numbered lists, to-dos, dividers, code | same | same (`- [ ]` has one space after `]`, the export has two) |
| nested list items | four spaces | a tab |
| quote | `> text`, then a `> ` line | `> text` |
| coloured or commented text | plain | `<span color="pink">…</span>`, `<span discussion-urls="…">…</span>` |
| page mention | `[Personal Mission Statement](Personal%20Mission%20Statement%20146d….md)` | `<mention-page url="https://app.notion.com/p/146d…"/>` |
| date mention | `@May 24, 2026` | `<mention-date start="2026-05-24"/>` |
| child page | `[Title](Title%20id.md)` | `<page url="…">Title</page>` |
| uploaded image | `![Kobe sprinted….jpg](Personal%20Vision/Kobe_sprinted….jpg)` | `![](https://prod-files-secure.s3…?X-Amz-Expires=300…)` — a signed URL valid five minutes |
| callout | `<aside>\n💡\n\ntext\n\n</aside>` | `<callout icon="💡">\n\ttext\n</callout>` |
| table | pipe table | `<table><tr><td>…` |
| toggle | (not observed) | `<details><summary>…</summary>…</details>` |
| times | local time (London; 12:39 UTC shown as 1:39 PM) | UTC ISO 8601 |
| property order | `Created time` before `Category` | JSON keys alphabetical — order must come from the data source schema |

Also observed: the export's *Document Hub (1)* twin is a real second
database in Notion, *Task Management (1)*, and its pages are currently in
the trash. The sync skips trashed pages, so the duplicate-credit problem
(A6 in `retrieval_improvements.md`) disappears as long as that database
stays in the trash.

**The corpus (measured)**

- 2,329 markdown files, 8.0 MB of text; 78 MB of images and attachments
  beside them (91 png, 19 csv, a pdf, a mov). 182 directories, 6 deep.
- 2,328 of 2,329 filenames end in a 32-hex page id. The one exception is
  an uploaded file, not a page. Directory names carry no id (or a short
  `abcd-wxyz` form when two siblings share a title).
- 1,332 files (57%) are database rows with property lines (`Created:`
  ×733, `Created time:` ×599, `Category:` ×508, `Tags:` ×357, `Last edited
  time:` ×129, then a long tail).
- Block types in use, by files containing them: headings 2,328; bullets
  1,476; dividers 677; nested lists 554; numbered lists 536; quotes 446;
  to-dos 381; child-page links 304; code fences 72; images 65; tables 30;
  equations 3; callouts 1.
- Human judgments store the chunk **text** and are joined by a hash of
  that text (`src/annotation/pooling.py:compute_chunk_key`, whitespace
  collapsed then sha256). Chunk ids are only the fast path
  (`evals/retrieval/qrels.py:match_chunk_key`). The judged text includes
  the property lines. Whitespace differences do not change a key; chunk
  *boundaries* do, and the chunker splits on blank lines first.
- Writing all 2,329 files to a fresh folder takes 0.18 s; reading one
  file takes 0.05 ms; ripgrep over the folder takes 40 ms.

## 5. Architecture

```
Notion workspace
   │  REST API · internal integration secret · read content · ≤3 req/s
   ▼
src/notion/client.py        NotionClient: paginated search listing,
                            page markdown, data source / database / block
                            lookups; token bucket; 429 back-off
src/notion/properties.py    property JSON → flat {name: value} and the
                            export's "Name: value" lines
src/notion/markdown.py      enhanced markdown → export-shaped markdown
                            (the normaliser) + the page frame
src/notion/mirror.py        mirror path naming; regenerates the folder
                            from notion_objects
src/notion/sync.py          the job: list → diff against notion_objects →
                            fetch markdown → normalise → clean → chunk →
                            embed → replace rows in every SYNC_CONFIG
                            table → record state → regenerate the mirror.
                            Returns a SyncReport.
   │
   ├─▶ chunks_qwen_notion · chunks_bge_m3_notion · chunks_fts_notion  (source = page_id)
   ├─▶ notion_objects · notion_sync_runs                (sync state, page markdown)
   └─▶ data/notion-mirror/<path>/<Title> <page_id>.md   (derived; app_config.data_dir)

scripts/sync.py             CLI: incremental (default) | --full | --reindex
                            | --dry-run | --limit N | --mirror-only
scripts/check_export_fidelity.py   normaliser vs the old export (oracle)
scripts/migrate_eval_ids.py        one-time rewrite of judgment ids
src/bootstrap.py            system prompt: read_file takes a chunk's path
main.py                     prints how stale the index is at REPL start
```

Existing pieces reused unchanged: `src/retrieval/cleaner.py:clean_text`,
`src/retrieval/chunker.py:chunk_text`, the embedders,
`retrieve.build_arm_indexer`. The sync indexes exactly the tables named in
`search_config.SYNC_CONFIG`: every dense arm's table with its embedder,
plus the lexical arm's table. Once `ACTIVE_CONFIG` is switched to those
tables (§6.6) every other chunk table (`chunks_qwen`, `chunks_bge_m3`,
`chunks_fts`, `chunks_qwen_title`, `chunks`) is unmaintained and dropped
in the cleanup phase.

## 6. Detailed design

### 6.1 Authentication and access

- One `.env` variable, `NOTION_TOKEN`, with a matching field
  `notion_token: str = ""` in `src/config.py` (`extra="forbid"` means a
  variable without a field breaks every import).
- The integration is created with **Read content** only. No comment or
  user-information capabilities, no write. A leaked secret can read notes,
  never change them.
- Access is granted from the integration's Access tab to every top-level
  page and database to be indexed. The export has 203 files and 12
  directories at its root, so this is a one-time click through the root
  pages, not per-note work. A page the integration cannot see is simply
  absent: the first `--full` run prints how many pages it listed so the
  count can be compared with the export's 2,329.

### 6.2 Discovery: list, then diff

The sync never walks the page tree. It lists.

**Listing.** `POST /v1/search`, empty query, filter object=page, sorted by
`last_edited_time` descending, 100 per request. About 24 requests for the
whole workspace. A second listing with object=data_source (about 20
results) gives the data sources; each database behind one is fetched once
with `GET /v1/databases/{id}` for its title and parent, and each data source
once with `GET /v1/data_sources/{id}` for its property schema order.

**Diff** against `notion_objects` (§6.8):

| listing says | table says | action |
|---|---|---|
| page id present | absent | **new**: fetch and index |
| `last_edited_time` newer than stored | present | **changed**: fetch and index |
| same `last_edited_time`, computed path differs from stored (an ancestor was renamed or the page moved) | present | **moved**: update `path` in the chunk metadata of every table; no fetch, no embedding |
| same `last_edited_time`, same path | present, `synced_at` set | **current**: skip, no request |
| `in_trash: true` | present | **gone**: remove chunks and row |
| absent from a full listing | present | **gone**: same |

Only new and changed pages cost requests beyond the listing. The mirror
folder is regenerated from the state table at the end of every run (§6.7),
so moves and deletions need no file bookkeeping.

**Incremental runs stop early.** Because the listing is newest-first, an
incremental run walks it until it reaches a page whose `last_edited_time`
is older than the **watermark**: the start time of the last successful run
minus ten minutes. The ten minutes absorb Notion's minute rounding and any
lag in its search index; the id-and-timestamp diff makes re-seeing a
current page free. A quiet day costs one request. Failed pages (fetch or
normalisation error) keep their old stored timestamp, so the next run
retries them.

**Full runs see deletions.** Stopping early can never notice a page that
vanished. `--full` walks the whole listing and removes every page in
`notion_objects` that it did not see or that is in the trash. Losing
integration access to a page counts as "gone" — intended: the index should
contain only what the integration can currently read.

**`--reindex`** ignores stored timestamps and re-fetches every listed page.
This is the procedure after a normaliser change; without it, pages
unchanged in Notion would never be re-rendered.

### 6.3 Tree, path and metadata from parent pointers

Every listed object names its parent. Following pointers upward through
`notion_objects` gives the path without traversal: *Life OS / Career / Job
Hunt 2025-2026*. The data source level is skipped in the path (a database
and its single data source share a title). A page whose parent is a
`block_id` (a page created inside a column or toggle) needs one
`GET /v1/blocks/{id}` to find its page; rare and cached.

Per page the sync stores, and copies into every chunk's `metadata`:

```
title, path, created_time, last_edited_time, url,
properties: {name: value}   # database rows only, flattened (§6.4)
```

`path` is the page's file path inside the mirror, relative to `data_dir`
(`Life OS/Career/Job Hunt 2025-2026 2abd….md`): its directories are the
ancestor titles, and it is exactly what `read_file` takes.

Metadata is **denormalised into the chunk rows**, not joined at query
time. A page change re-indexes all of that page's chunks anyway (§6.6),
so keeping a copy per chunk costs nothing extra, leaves the arms' row shape
`{id, text, source, metadata, score}` untouched, and lets a future arm
filter on `metadata->>'created_time'` with no join. Today only `title` is
read from metadata (`indexer.py:174`, the FTS generated column,
`search.py:format_chunk`); the extra keys are ignored until something asks
for them.

### 6.4 Content: one markdown request per page, then normalise

For each new or changed page: `GET /v1/pages/{page_id}/markdown`. If
`truncated` is true (not expected in this workspace), each id in
`unknown_block_ids` is fetched the same way and appended. The result is
**normalised** into the export's markdown, because the human labels join
on chunk text (§4) and 57% of notes carry property lines inside that text.

**Why normalise at all, rather than store Notion's dialect as-is.** Three
reasons. The labels: different spacing changes chunk boundaries, and
different text orphans 171 judgments. The models: `<span>`, `<empty-block/>`
and signed URLs are noise to embed and tokens to pay for. The reader: the
mirror should be readable by a human and by `grep`. The normaliser is
small, and the export folder measures it (§9).

**Page frame**, exactly as the export:

```
# {title}
                              ← blank
{Name}: {value}               ← one line per property, database rows only,
...                              in the data source's schema order
                              ← blank
{normalised body}
```

The title comes from the page object's title property. If the endpoint's
markdown already begins with `# {title}` (open point in §4), the frame does
not add a second one. Plain pages have no property lines.

**Property values**, matching the export's formatting (the fidelity check
in §9 confirms each rule):

| property type | rendered as |
|---|---|
| title | omitted (it is the heading) |
| `created_time`, `last_edited_time`, date | `April 2, 2026 1:39 PM`; date-only when no time; in the local timezone (observed: 12:39 UTC → `1:39 PM`) |
| select, status | the option name |
| multi_select | names joined by `, ` |
| checkbox | `Yes` / `No` |
| number, url, email, phone | as text |
| rich_text | plain text |
| relation | titles of the related pages, from `notion_objects`, joined by `, ` |
| people | display names |
| formula, rollup | the computed value as text |
| files | file names |

The same flattening produces the `properties` dict stored in metadata,
with dates kept as ISO strings there.

**Normaliser rules**, applied line by line to the enhanced markdown
(Notion's specification is the MCP resource
`notion://docs/enhanced-markdown-spec`; the export forms come from the
files under `data/notion-export-markdown`):

| enhanced markdown | export form |
|---|---|
| `<empty-block/>` | an empty line |
| one newline between blocks | a blank line after every block that is not a list item; consecutive list items (`-`, `1.`, `- [ ]`) stay contiguous |
| leading tabs (nesting) | four spaces per tab |
| `> text` | `> text` followed by a `> ` line |
| `<span …>text</span>` (colour, underline, discussion anchors) | `text` |
| `{color="…"}`, `{toggle="true"}` attribute lists at line end | removed |
| `<mention-page url="…/p/{id}"/>` or `<mention-page url>Title</mention-page>` | `[Title](relative mirror path, URL-encoded)`, title and path from `notion_objects` |
| `<page url="…">Title</page>`, `<database url="…">Title</database>` | the same link form |
| `<mention-date start="YYYY-MM-DD" [startTime]/>` | `@Month D, YYYY` with ` h:mm AM` when a time is present |
| `<mention-user …>Name</mention-user>` | `@Name` |
| `![caption](signed prod-files-secure URL)` | `![name](name)` with the file name from the URL path; external image URLs unchanged |
| `<file src>`, `<pdf src>`, `<video src>`, `<audio src>` | `[caption or name](name)` |
| `<callout icon="💡">\n\ttext\n</callout>` | `<aside>\n💡\n\ntext\n\n</aside>` |
| `<table …>…</table>` | a pipe table; first row as header when `header-row="true"` |
| `<details><summary>text</summary>children</details>` | `- text` with children indented (measured against the export if any toggle exists there; else kept as the simplest readable form) |
| `<columns>`, `<column>`, `<synced_block>`, `<synced_block_reference>` | wrappers removed, children kept in order |
| `<table_of_contents/>`, `<embed>`, `<unknown …/>`, `<meeting-notes>` (transcript excluded) | removed; counted in the run report |
| `$`equation`$` inline, `$$` block | `$equation$`, `$$` block unchanged |
| backslash escapes (`\*`, `\[`) | the character itself |

Everything else — headings, bullets, numbered lists, to-dos, dividers,
code fences, bold, italic, strikethrough, inline code, links — is already
identical and passes through.

Uploaded images and attachments are **not downloaded**. The mirror holds
text only (8 MB, not 92 MB). Chunks that referenced a local image in the
export will differ in the link target; the fidelity check reports how many.

**Fallback.** If the markdown endpoint proves metered or is withdrawn,
`GET /v1/blocks/{id}/children` still exists; a block-tree renderer
targeting the same export shape would replace the normaliser behind the
same `render_page` signature. Not built now.

### 6.5 Chunk identity

A chunk id is `"{page_id}#{chunk_index}"`.

- `page_id` is Notion's page id without dashes, 32 hex characters — the
  same string the export put at the end of every filename, so the
  old-to-new mapping needs no lookup: `Journal/Take responsibility
  336d52d026fc8076ade8f7b2612f1fef.md#0` → `336d52d026fc8076ade8f7b2612f1fef#0`.
- `chunk_index` is the chunk's position within the page: `chunk_text`
  splits the page's cleaned markdown into pieces of at most 2,000
  characters and the pieces are numbered 0, 1, 2… in order
  (`scripts/ingest.py:41` does this with `enumerate` today; the sync does
  the same). `…#3` is the fourth piece of that page. An edit near the top
  of a page can shift every later boundary, so indices after the edit are
  not stable — which is why labels re-attach by text hash, not by index.

The `source` column of every chunk table holds the page id. Its meaning
changes from "file path" to "page id"; the consumers are listed in §8.
Page ids are stable across renames and moves; export paths were not (the
*Document Hub* → *Task Management* rename had already changed the path of
136+ notes).

### 6.6 Indexing: replace a page's rows in every table, both embedders at once

Per new or changed page, in this order:

1. Fetch markdown, normalise, build the frame, flatten properties.
2. `clean_text` → `chunk_text` → `Document(id, text, source=page_id,
   metadata)` per chunk, exactly as `scripts/ingest.py` does.
3. For every dense arm in `SYNC_CONFIG` (§6.8): embed with that arm's
   embedder and upsert into that arm's table (`PgVectorIndexer.index`,
   existing). For the lexical arm: upsert text and metadata into its table
   (new `PgFtsIndexer.index`, no embedding; the `tsv` column is generated).
   Then, in every table, **delete rows of this `source` whose id is not in
   the new id set** (new method on both indexers). Upsert-then-trim never
   leaves a page without chunks, and a page that shrank leaves no orphans.
4. Upsert the page's `notion_objects` row with the normalised markdown,
   `synced_at = now()` and the new `chunk_count`.

A moved page: `update_metadata(source, metadata)` in every table (new
method, one `UPDATE` each); the row's `path` is updated. A gone page:
delete its rows from every table by `source`, delete its row.

At the end of the run the mirror folder is regenerated (§6.7).

Both embedders run in the same process and the same pass. Today
`scripts.ingest` runs per embedder, which allows the two dense tables to
drift apart; the sync makes drift impossible by construction. Search
already loads both models, so memory is unchanged.

**Fresh tables, not a truncate.** The sync writes to its own tables,
`chunks_qwen_notion`, `chunks_bge_m3_notion` and `chunks_fts_notion`,
declared as `SYNC_CONFIG` in `search_config.py` (the same three arms as
`ACTIVE_CONFIG` with those table names; `build_arm_indexer`'s prefix rule
already accepts them). The export-built tables stay untouched and the
shipped search keeps working while the first sync runs. An eval
experiment `rrf-3arm-k5-notion` points at the new tables, so old and new
corpus can be scored side by side on the same labels. When the fidelity
gate and the self-test pass, `ACTIVE_CONFIG` is switched to the same
tables (one line) and the old tables are dropped in the cleanup phase.
Rollback until then is reverting that line.

Writes are per table, not one transaction across tables (the indexers open
their own connections). A crash mid-page leaves at worst a page indexed in
one table and not the other for one run: the `notion_objects` row is
written last, so the page is re-done on the next run. Fusion tolerates a
chunk missing from one arm in the meantime.

**Not in this version: skipping unchanged chunks.** Re-embedding only
chunks whose text hash changed was in the original note. It saves work
only on edited pages, which an incremental run has few of, and it would
need a hash column and a second code path in the indexers. Dropped for
simplicity; listed as a follow-up in §12.

### 6.7 The disk mirror

`data/notion-mirror/` (repo root), the new default of `app_config.data_dir`.
The agent's `read_file`, `list_dir` and `grep` tools are unchanged; they
read this folder instead of the export.

The mirror is **derived, never edited in place**. Every page's normalised
markdown lives in `notion_objects.markdown`; at the end of each run the
sync writes the whole folder afresh into `data/notion-mirror.tmp` and swaps
it in with two renames, so readers never see a half-written folder. A
page that moved lands in its new place, a gone page is simply not written,
and no code tracks old file paths. `scripts.sync --mirror-only` rebuilds
the folder from the database with no network, which is also how a fresh
checkout gets a mirror from a restored database.

Layout mirrors the export so paths stay human-readable and the
normaliser's child-page links match:

- A page is `"{safe_title} {page_id}.md"` inside the directory of its
  parent's path. `safe_title` strips the characters the export strips
  (`/ \ : * ? " < > |`), collapses whitespace, and falls back to `Untitled`.
- A page with child pages also gets a directory named `safe_title` beside
  its file; two sibling directories with the same title get the short
  `{id[:4]}-{id[-4:]}` suffix, as the export does.
- Database rows sit under `{database title}/`.

Size and speed, measured on the export: 2,329 files, 8 MB, written in
0.18 s — cheap enough to regenerate on every run; one `read_file` is
0.05 ms; `rg` over the folder is 40 ms. Disk reads are not slower than the
database for this — Postgres is for similarity search over chunks; the
folder is for whole-note reads and grep, which is what those tools do.

The old export folder is kept, read-only, as the normaliser's oracle (§9)
until the fidelity check has passed and the datasets are migrated; then it
is deleted.

### 6.8 Sync state

Two tables, created by the sync's own `ensure_schema()`:

```
notion_objects
  id               text primary key   -- 32-hex, no dashes
  kind             text               -- page | data_source | database
  title            text
  parent_id        text               -- null for workspace
  parent_kind      text               -- page | data_source | database | workspace | block
  path             text               -- ancestor titles joined by " / "
  url              text
  created_time     timestamptz
  last_edited_time timestamptz
  properties       jsonb              -- flattened; pages only
  schema_order     jsonb              -- property names in order; data sources only
  mirror_path      text               -- relative to data_dir; pages only
  markdown         text               -- normalised page text; the mirror is written from it
  chunk_count      integer
  listed_at        timestamptz        -- last seen in a listing
  synced_at        timestamptz        -- null until content is indexed

notion_sync_runs
  id, mode (incremental|full), started_at, finished_at, status,
  pages_listed, pages_indexed, pages_removed, pages_failed, requests
```

The incremental watermark is `started_at` of the newest run with status
`ok`. `synced_at` being null distinguishes "listed but never fetched"
(a failed page) from "current".

### 6.9 Rate limiting, retries, failure handling, resumability

- `NotionClient` is synchronous, built on `httpx` (already installed as a
  dependency of the MCP SDK; declared explicitly in `pyproject.toml`). It
  wraps five calls: search (paginated), page markdown, data source,
  database, block. A token bucket allows three requests per second.
  Single-threaded: with round trips around 300 ms one thread nearly
  saturates the limit, and concurrency can be added inside the client
  later without changing callers.
- HTTP 429 and 529: sleep for `Retry-After` seconds, retry, at most five
  attempts. Other 5xx: exponential back-off, five attempts. 401/403: stop
  the run — the secret, the access grant or (403 with
  `workspace_credits_exhausted`) the endpoint's entitlement is wrong and
  every request will fail; the message names which. 404 on a page: treat
  as gone.
- A page that fails to fetch or normalise is logged, counted in
  `pages_failed`, skipped, and left with its old `synced_at`/timestamp so
  the next run retries it. The run continues.
- Interruption is safe: state is per page and written last, so a killed
  run resumes by listing again; pages already current are skipped by the
  diff. Newest-first order means whatever got in is the freshest content,
  and the first sync becomes useful within minutes — recent months are
  searchable while old material fills in behind.

### 6.10 Entry points

**Library.** `src/notion/sync.py:run_sync(mode="incremental"|"full",
reindex=False, limit=None, on_progress=None) -> SyncReport`. Plain
function, plain arguments, a report dataclass back (the counts in
`notion_sync_runs` plus the failed page ids and the tags the normaliser
dropped). The future sync button in the web chat is a `POST /api/sync`
route in `src/chat/app.py` that calls this in a background thread and a
status route the page polls; nothing else is needed on this side.
`on_progress` exists so that route can report "120 of 340 pages" while it
runs.

**CLI.** `uv run python -m scripts.sync` with `--full`, `--reindex`,
`--dry-run` (list and diff, print what would change, touch nothing),
`--limit N` (index at most N pages, newest first — a smoke run against the
real workspace), `--mirror-only` (rebuild the folder from the database, no
network). Prints the report; exit code non-zero when the run failed or any
page failed.

**REPL.** `main.py` prints one line at start when the sync tables exist:
"notes index: last synced 12 min ago (incremental), last full listing 6 h
ago". No automatic sync; the owner decided runs are manual for now.

### 6.11 Configuration

| variable | field | default |
|---|---|---|
| `NOTION_TOKEN` | `notion_token` | `""` — sync refuses to run when empty |
| `DATA_DIR` | `data_dir` | `../data/notion-mirror` (was `../data/notion-export-markdown`) |

The API version, rate and retry counts are constants in the client, not
configuration.

## 7. Migrating the eval datasets

The datasets refer to notes by export path. They must refer to page ids.

**Generated queries** (`data/datasets/queries.json`, 294 queries): each
record's `source_file` is an export path ending in the 32-hex id. No data
rewrite: `evals/retrieval/qrels.py:load_file_queries` derives the page id
from that filename with a regex, and `score_generated` compares it with the
row's `source` as before. A query whose file has no id (the one uploaded
file) can never hit and is reported.

**Judgments** (`data/annotations.json`, 19 queries, 171 judgments): a
one-time script, `scripts/migrate_eval_ids.py`, run after the first full
sync:

1. For each judgment's `sources[].chunk_id`, take the page id from the
   filename hash.
2. Load that page's chunks from `chunks_qwen_notion`, hash each with
   `compute_chunk_key`, and find the chunk whose key equals the judgment's
   key. Rewrite `chunk_id` to its new id and `metadata.source` to the page
   id; add `metadata.path`.
3. If no chunk of the page has that text any more (the page was edited in
   Notion since the export, or the normaliser rendered it differently),
   leave the entry untouched and list it in the migration report as
   **orphaned**, with the page's `last_edited_time` so the reason is
   visible. The label keeps counting as a positive in the ideal ordering,
   so recall on that query is a floor — the same caveat every eval number
   already carries.
4. Write the file back, keeping a copy of the original beside it.

The split (`data/datasets/split.json`) is keyed by query text and is not
touched. It must never be regenerated.

**Self-test** (`evals/retrieval/selftest.py`): today it compares pooled
chunk ids with retrieved ids. It changes to compare by chunk key, and for
every pooled judgment it does not find, it checks whether the judgment's
text still exists among the page's chunks:

- text present, not retrieved at depth 10 → **failure** (the join or the
  retriever broke);
- text absent → **reported, not a failure** ("N judgments whose page
  changed since labelling").

This is the distinction the old self-test could not make.

**Recorded runs.** `compare` reads `metrics.json` only, so old runs stay in
the table. `diagnose` across an old and a new run mixes id schemes and is
not meaningful; use it within runs of the same scheme. After migration the
shipped configuration `rrf-3arm-k5` is re-run and recorded; the difference
from `20260901T080825Z-rrf-3arm-k5` measures corpus drift (new and edited
pages since 2026-08-09) plus orphaned labels, not a retrieval change. That
run becomes the baseline for future experiments.

## 8. Component changes

**New**

| file | contents |
|---|---|
| `src/notion/client.py` | `NotionClient(token, requests_per_second=3.0, transport=None)`: `iter_search(kind)`, `get_page_markdown(id)`, `get_data_source(id)`, `get_database(id)`, `get_block(id)`; `request_count`. Injectable `httpx` transport for tests. |
| `src/notion/properties.py` | `flatten_properties(page) -> dict`, `format_property_lines(properties, schema_order) -> str` |
| `src/notion/markdown.py` | `normalise(enhanced: str, links: LinkResolver) -> str` (the rules in §6.4), `render_page(page, body, property_lines) -> str` (the frame) |
| `src/notion/mirror.py` | `build_mirror_path(page, path_of_parent, siblings) -> Path`, `regenerate_mirror(rows, data_dir)` (write to `.tmp`, swap) |
| `src/notion/sync.py` | `ensure_schema`, `plan_run` (the diff), `index_page`, `move_page`, `remove_page`, `run_sync`, `SyncReport` |
| `scripts/sync.py` | CLI over `run_sync` |
| `scripts/check_export_fidelity.py` | the oracle check, §9 |
| `scripts/migrate_eval_ids.py` | §7 |
| `tests/test_notion_client.py`, `test_notion_markdown.py`, `test_notion_properties.py`, `test_notion_mirror.py`, `test_notion_sync.py`, `test_migrate_eval_ids.py` | §9 |

**Modified**

| file | change |
|---|---|
| `src/retrieval/indexer.py` | `PgVectorIndexer.delete_source_except(source, keep_ids)`, `delete_by_source(source)`, `update_metadata(source, metadata)` |
| `src/retrieval/lexical.py` | `PgFtsIndexer.index(documents)` becomes a real upsert (today it raises); the same three methods |
| `src/retrieval/search_config.py` | `SYNC_CONFIG` (the three arms over the `_notion` tables); later `ACTIVE_CONFIG = SYNC_CONFIG` |
| `evals/retrieval/experiments.py` | `rrf-3arm-k5-notion`, the shipped configuration over the new tables |
| `src/config.py` | `notion_token`; `data_dir` default |
| `src/tools/search.py` | `format_chunk` returns `{rank, chunk_id, page_id, path, title, text}`; `source` is renamed because it is no longer a path; `path` is what `read_file` takes; tool description and the summariser stub updated |
| `src/bootstrap.py` | system prompt says `read_file` on a chunk's `path` (today: `source`) |
| `main.py` | staleness line at REPL start |
| `evals/retrieval/qrels.py` | `load_file_queries` maps filename → page id; `NOTES_PREFIX` removed |
| `evals/retrieval/selftest.py` | compare by chunk key; report "page changed since labelling" separately |
| `evals/retrieval/runner.py` | `build_result_rows` adds `path` from metadata (optional, for diagnose output) |
| `scripts/search.py` | print title and path, not the bare page id |
| `scripts/ingest.py` | docstring only: it is the path for folders that are not a Notion workspace (`mem-export`), and it must be pointed at its own tables, never the `_notion` ones |
| `pyproject.toml` | declare `httpx` |
| `tests/test_search_tools.py`, `tests/test_qrels.py` | new shapes |
| `docs/architecture.md`, `AGENTS.md`, `docs/designs/retrieval_overview.md`, `docs/testing.md` | ingestion from Notion, the mirror, the id scheme, the new tables, commands |

**Unchanged**: cleaner, chunker, embedders, fusion, `retrieve.py`,
`search_config.py`, the annotation UI (it reads `metadata` and `source`
generically), `src/tools/file.py`, `src/mcp_client.py`, Gmail tools.

## 9. Testing and verification

Per `docs/testing.md`: every new behaviour has a test, tests test logic
not plumbing, database tests use the `test_db_url` fixture.

**Unit (no network, no database)**

- Client: pagination follows `next_cursor`; the token bucket spaces
  requests; 429 sleeps for `Retry-After` and retries; 401 raises; the
  version header is sent; `truncated` responses fetch `unknown_block_ids`.
  All via `httpx.MockTransport`.
- Normaliser: one case per rule in §6.4, each a small enhanced-markdown
  string and its export form, taken from real pages of this workspace with
  ids scrubbed; the page frame with and without properties; dropped tags
  counted.
- Properties: each type in the table; date formatting and timezone;
  schema order.
- Mirror: naming, sanitising, sibling collisions, untitled pages;
  regeneration into a temporary directory then swap — a moved page lands
  in its new place, a gone page is absent, the old folder is gone.
- Sync planner: given a listing and a table state, the new/changed/moved/
  current/gone sets; the early-stop watermark with the ten-minute overlap;
  `--reindex`.
- Migration script: a three-judgment fixture — one that maps, one whose
  text moved to a different index, one orphaned.

**Postgres-marked**

- Upsert-then-trim leaves exactly the new ids for a page that grew, shrank
  and stayed the same; removal by source; metadata-only update for a moved
  page leaves text and embeddings untouched; FTS upsert; the state tables.

**Against the real workspace, scripted (not CI)**

1. **Normaliser fidelity, the gate for everything else.**
   `scripts.check_export_fidelity --export ../data/notion-export-markdown
   [--sample N] [--judged-first]` fetches every page that has an export
   file and was last edited before 2026-08-10, normalises it, runs both
   texts through `clean_text` and `chunk_text`, and compares the chunk-key
   sequences. It reports pages compared, share with identical chunk
   sequences, share with at least one identical chunk, and the commonest
   first-differing lines. Acceptance: **at least 95% of unedited pages
   chunk identically, and every relevant note in the judged set (59 notes)
   chunks identically or has a documented reason.** `--judged-first`
   orders the check by the judged set so the answer for the labels comes
   within a minute rather than after the full pass (about 13 minutes at
   three requests per second).
2. `scripts.sync --full --limit 20`: twenty newest pages appear in the
   mirror and in every table with matching ids; `scripts.search` on one of
   them returns a chunk with the new metadata.
3. `scripts.sync --full` into the empty `_notion` tables: page count
   matches the listing; duration and request count recorded in
   `notion_sync_runs`; the old tables and the shipped search are untouched
   meanwhile.
4. Edit a page in Notion, run `scripts.sync`: the page is re-indexed within
   one run. Rename a parent page: the children's `path` changes in every
   table and the mirror, with no embedding. Move a page to trash, run
   `--full`: its chunks are gone and its file is absent from the
   regenerated mirror.
5. `scripts.migrate_eval_ids`, then `evals.retrieval.selftest` against the
   new tables: zero failures; the "page changed since labelling" count is
   recorded in the design's follow-up notes. Then
   `evals.retrieval.run rrf-3arm-k5-notion` and `compare` against
   `rrf-3arm-k5` on the old tables — same labels, two corpora.

## 10. Cost and performance estimates

| | estimate | basis |
|---|---|---|
| Full listing | ~24 requests, ~10 s | 2,329 pages / 100 per request |
| First full sync, API side | ~2,400 requests, 13–15 min at 3 req/s | one markdown request per page, ~24 listing, ~20 data sources and databases; no per-block requests |
| First full sync, embedding side | the same as running `scripts.ingest` for both embedders today; the long pole | 5,979 chunks × 2 models, local |
| Incremental run, quiet day | 1 request, under a second | early stop at the watermark |
| Incremental run, N edited pages | 1 request and 2 embeddings per page | |
| Mirror regeneration, every run | 8 MB, 2,329 files, 0.2 s | measured |
| State tables | 2,400 rows, ~8 MB of page markdown | |

Had the block-children endpoint been used instead, the first sync would
have needed about 5,000 requests (one per page plus one per block with
nested children), roughly 30–45 minutes.

## 11. Risks

| risk | effect | mitigation |
|---|---|---|
| Normaliser output differs from the export | judged labels orphaned (their text no longer exists) | the fidelity oracle and its 95% / judged-set gate before migration; `--reindex` to re-render after normaliser fixes |
| Property dates rendered in the wrong timezone, format or order | every database-row chunk differs → most labels orphaned | the oracle catches it on the first sample; formatting is one function; order comes from the data source schema |
| The markdown endpoint turns out to be metered ("workspace credits") or is withdrawn | sync stops with 403 | the client stops on the first such error and names it; fallback is the block-children renderer behind the same `render_page` signature (§6.4) |
| Enhanced markdown syntax changes | rules stop matching | the run report counts tags the normaliser dropped, so a new tag shows up as a number, not silence |
| Notion search index lags or timestamps round | an edit missed by an incremental run | ten-minute overlap; `--full` re-lists everything |
| Two id schemes in one table | duplicate chunks, wrong fusion | the sync has its own tables; nothing else writes to them |
| First sync interrupted | partial index | per-page state, newest-first, re-run resumes |
| Page not connected to the integration | silently missing | the first run prints listed vs expected counts; Access tab grants in bulk |
| The twin database *Task Management (1)* is restored from the trash | duplicate notes return (A6) | nothing in the sync; a note in the docs; dedupe is a listed follow-up |

## 12. Decisions taken, questions still open, follow-ups

**Taken (with the reason)**

- REST API with an internal integration, not the hosted MCP server:
  non-expiring secret; a background job cannot re-consent every eight
  hours.
- Page markdown endpoint, not the block tree: one request per page instead
  of several, no recursion, no pagination of blocks, and the same renderer
  the hosted MCP server uses. The block API stays as the documented
  fallback.
- Normalise to the export's shape rather than store Notion's dialect:
  keeps the labels, keeps the embeddings clean, keeps the mirror readable.
  About fifteen line rules, measured by the oracle.
- Page id as the chunk `source`: stable across renames and moves; maps to
  the export by filename hash.
- Metadata denormalised into chunk rows, not joined: a page change
  re-indexes its chunks anyway; arms keep their row shape.
- Both embedders in one pass, driven by `ACTIVE_CONFIG`: the tables cannot
  drift.
- Upsert-then-trim, not delete-then-insert: a page is never chunkless.
- Fresh `_notion` tables, not a truncate: the old index keeps working
  during the first sync, old and new corpus score side by side on the same
  labels, rollback is one line, and two id schemes can never meet.
- The mirror is regenerated from the database after every run, not edited
  file by file: 0.2 s buys the removal of all move, rename and delete
  bookkeeping, and a `--mirror-only` rebuild for free.
- No chunk-hash skip in v1: little saving, extra code path.
- `httpx` over the `notion-client` SDK: five endpoints, an injectable
  transport for tests, already installed.
- Manual runs only: owner's decision; a web-chat button and a scheduler
  call the same `run_sync`.

**Still open**

- Whether the REST markdown body includes the title heading; settled by
  the first oracle run, and the frame code handles both.
- Timezone for property dates: local zone until the oracle says otherwise;
  a config field if it does.
- Whether to download uploaded images and attachments into the mirror
  (78 MB). Not in v1; `read_file` on a note would still show the file
  name.
- Whether `scripts.ingest` should be kept at all once the mirror exists,
  or reduced to the `mem-export` use case.

**Follow-ups, in the likely order**

1. Sync button in the web chat: `POST /api/sync` and a status route in
   `src/chat/app.py` over `run_sync`, a button and progress line in
   `sumi-frontend/`.
2. A scheduler (launchd every 15 minutes, with the script itself running a
   full listing when the last one is older than a day).
3. Agent-side Notion MCP tools (`fetch`, `query-data-sources`): OAuth with
   PKCE via the MCP SDK's `OAuthClientProvider`, a token store under
   `secrets/`, an allowlist, one `register_mcp_tools` call — the Gmail
   pattern.
4. Retrieval experiments on the new metadata: a date filter or boost (B1),
   path and tags in the lexical arm (B2), measured with the harness.
5. Skip re-embedding unchanged chunks by text hash, if incremental runs
   ever feel slow.
6. Delete the export folder and the `chunks` / `chunks_qwen_title` tables.

## 13. Implementation phases and first-time procedure

Each phase is its own plan and PR; each ends green (`uv run pytest`,
`uv run ruff check .`) and with the docs it makes false corrected.

1. **Client, normaliser, oracle.** `src/notion/client.py`, `properties.py`,
   `markdown.py`, their tests, `scripts/check_export_fidelity.py`,
   `notion_token`, `httpx`. No database change. Exit: the fidelity gate in
   §9 passes.
2. **Sync.** Indexer delete and metadata methods, FTS upsert,
   `SYNC_CONFIG`, `mirror.py`, `sync.py`, `scripts/sync.py`, `data_dir`
   default, the search tool's `path`, REPL staleness line. Exit: checks
   2–4 in §9.
3. **Eval migration and switch.** `qrels.py`, `selftest.py`,
   `migrate_eval_ids.py`, the `rrf-3arm-k5-notion` experiment; run the
   migration; record the new baseline; set `ACTIVE_CONFIG` to the new
   tables; update `retrieval_overview.md`. Exit: check 5 in §9.
4. **Docs and cleanup.** `architecture.md`, `AGENTS.md`, delete the export
   folder, drop the old chunk tables, move the plan note to completed.

First-time procedure for the owner (also the "new user" path, minus the
migration):

1. Create the internal integration with Read content only; put its secret
   in `.env` as `NOTION_TOKEN`.
2. In the integration's Access tab, grant the top-level pages and
   databases to index.
3. Start Postgres. `uv run python -m scripts.sync --full --limit 20`, then
   `scripts.search` on a known note. Then `scripts.sync --full`. The old
   index keeps serving searches throughout.
4. `uv run python -m scripts.migrate_eval_ids`, then
   `evals.retrieval.selftest`, then `evals.retrieval.run
   rrf-3arm-k5-notion` and `compare`.
5. Switch `ACTIVE_CONFIG` to the new tables. A new user without labels
   skips step 4 and switches after step 3.
6. From then on: `uv run python -m scripts.sync` when fresh notes are
   wanted; `--full` occasionally to drop deleted pages.
