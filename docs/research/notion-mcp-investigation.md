# Notion MCP as the Notes Backend: Investigation

Could sumi drop the Notion export, the Postgres tables and the local embedding
models, and instead have the agent call Notion's hosted MCP server directly?
This document records what was measured on 2026-09-03, what the switch would
gain and lose, and the options that follow. Paths are relative to
`sumi-backend/` unless noted.

Terms used below:

- **Notion MCP** — the remote server Notion hosts at `https://mcp.notion.com/mcp`.
  A client authenticates with OAuth and calls tools such as `search`, `fetch`
  and `query-data-sources` over the Model Context Protocol (MCP), the same
  protocol sumi already uses for Gmail (`docs/mcp-integration.md`).
- **Workspace search** — Notion's keyword search. It is what `search` runs
  when the workspace does not have Notion AI.
- **AI search** — Notion's semantic search. It needs a Business or Enterprise
  plan with Notion AI. **This workspace does not have it**, so it was not
  measured; the `search` tool refuses `content_search_mode: "ai_search"` with
  "AI search is not available".
- **Note-level recall** — a query counts as a hit if any chunk (sumi) or the
  page itself (Notion) of a relevant note is in the top 10. The judged labels
  are per chunk; Notion returns pages, so this is the only comparison that is
  fair to both. `file_recall@10` in `retrieval_overview.md` is the same idea.

## Short answer

Replacing the backend with Notion MCP as it is available to this workspace
today would roughly halve retrieval quality. On the same queries, Notion's
workspace search found 20 of the 59 relevant notes the shipped configuration
finds 50 of, and missed every relevant note on 6 of the 17 judged queries the
shipped system answers. It found nothing the shipped system misses.

What Notion MCP adds is real and is exactly what the local stack lacks: live
data (the export is three weeks stale and already misses one judged query's
answer), structured queries over Notion databases (a one-line SQL query found
the "August 1, 2026" check-in the retrieval stack can only stumble on), page
metadata (path, dates, tags, comments), and write access.

The recommendation is therefore not to replace but to add: keep the local
retrieval stack as `search_notes`, register Notion MCP's `fetch` and
`query-data-sources` as further agent tools, and treat "sync the corpus from
Notion instead of from an export" as the route to freshness. Replacing
retrieval only becomes a live question if the workspace gains Notion AI, and
even then it must be re-measured with the method below.

## What the two backends are

| | Today: export → pgvector | Notion MCP |
|---|---|---|
| Corpus | 2,329 markdown files exported 2026-08-09, 5,979 chunks | The live workspace |
| Unit returned | Chunk (≤2,000 chars) with `chunk_id`, `source`, `title`, `text` | Page: `id`, `title`, `url`, `path`, `timestamp`, a keyword `highlight` (≤500 chars). No content; a second call (`fetch`) returns the whole page |
| Ranking | Two dense arms (Qwen3, BGE-M3) + Postgres full-text search, fused with reciprocal rank fusion, `rrf_k=5`, all tunable | Notion's ranking. Keyword on this plan, semantic with Notion AI. Only levers: query text, filters (`page_url`, `data_source_url`, date, creator), `page_size` ≤ 50 |
| Metadata | Title only | Path, created/last-edited time, database properties (tags, dates), comments, mentions, child pages |
| Freshness | Manual re-export + `scripts.ingest` (two embedders) + `scripts.build_fts` | Live |
| Writes | None | Create/update pages, comments, databases |
| Runs where | Local: Postgres + two sentence-transformers models | Network call; OAuth token; rate limits |
| Measurable | Yes: chunk-level judgments, `evals/retrieval/` | Note-level only, via the page-id mapping below |

The export filename carries the Notion page id (`Personal Vision
146d52d026fc800dbc2ae01e2f94d03b.md` ↔ page `146d52d0-26fc-800d-…`). Every
relevant note in the judged set and every source note in the generated sample
mapped this way, so any page-level retriever can be scored against the existing
datasets at note level without new labels.

## Method

All Notion calls went through the Notion MCP connector available in this
Claude Code session, against the same workspace the export came from
("John's Notion", one user). Each query was sent to `search` once, as typed,
with `page_size=10` and highlights off, mirroring `search_notes` (unthresholded
top 10, query passed through unchanged). Results were recorded by page id and
compared with the shipped run `20260901T080825Z-rrf-3arm-k5` on the same
queries, both at note level.

Two query sets:

- **Judged set**: all 17 scored real queries (`data/annotations.json`),
  59 relevant notes between them.
- **Generated set**: 20 of the 70 non-template val queries
  (`random.seed(17)`), scored on whether the source note appears. Template
  notes (Daily Check In etc.) were excluded because the same passage exists in
  many copies and the generated set cannot tell them apart (`retrieval_improvements.md`, A3).

Caveats. This is one manual pass, not a harness run: no latency was recorded,
and the connector may differ from a direct `mcp.notion.com` client in ways
that do not affect ranking. The judged labels come from pools built by the
local retrievers, so a Notion hit outside the pool would score as a miss — but
Notion produced no hit the shipped system lacked, so that bias did not bite
here. The shipped numbers are note-level and therefore higher than the
chunk-level ndcg in `retrieval_overview.md`.

## Results

### Judged set (17 real queries)

| | shipped `rrf-3arm-k5` | Notion workspace search |
|---|---|---|
| relevant notes found in top 10 | 50 / 59 (0.85) | 20 / 59 (0.34) |
| queries with ≥1 relevant note in top 10 | 17 / 17 | 11 / 17 |
| note-level MRR@10 | 0.831 | 0.574 |
| distinct notes across the 170 top-10 slots | 126 | 98 |

Per query, ranks at which relevant notes appeared:

| query | relevant notes | shipped | Notion |
|---|---|---|---|
| what does napoleon say about leadership? | 2 | 1, 3 | — |
| what made napoleon so great? | 1 | 1 | — |
| do i have any good ideas on creative workflows? | 2 | 10 | — |
| where did john knoll work? | 2 | 1, 2 | 1 |
| john knoll | 3 | 1, 2, 3 | 1, 2, 3 |
| summarise what's in my personal vision doc | 1 | 5 | 1 |
| how can i speak more eloquently? | 1 | 1 | — |
| what are the criteria for my dream jobs? | 4 | 2, 6, 10 | 1 |
| what tasks did i put down on august 1, 2026 | 2 | 1, 2 | — |
| what do i imagine myself doing when running 787? | 8 | 1, 2, 3, 4, 5 | 1, 3, 4 |
| how does ichiro suzuki stay so fit? | 2 | 1, 2 | 1, 2 |
| what are good questions to ask someone when first meet them? | 5 | 1, 6, 9, 10 | 1 |
| how to make a good first impression? | 2 | 3, 9 | — |
| what do good product managers do that others don't? | 6 | 1, 2, 3, 4, 6 | 1 |
| what made edwin land successful? | 6 | 1, 2, 4, 6, 9, 10 | 1, 2 |
| what do elon musk and edwin land have in common | 8 | 1, 2, 3, 4, 5, 6, 8 | 2, 3, 7 |
| what did jobs say in his speech? | 4 | 1, 2, 3 | 4, 9 |

The pattern is the one a keyword engine predicts. Notion does well when the
query contains the note's title words (*john knoll*, *edwin land*, *ichiro
suzuki*, *personal vision*, *787*) and fails on question-shaped queries whose
answer uses other words: the Napoleon quote lives in a note titled *Take
responsibility*; "speak more eloquently" is answered by *Public Speaking*.

Its top 10 is also crowded by a few large, recently edited hub pages that
contain common query words. *Personal Vision* appeared in the top 10 for 11
of the 17 queries, *Personal Mission Statement* for 9, *Job Hunt 2025-2026*
for 8 and *Plan for the week @Monday* for 7, regardless of topic. Scoping the
Napoleon query to the Journal database (`page_url`) did surface *Take
responsibility*, at rank 7, so the agent could recover some recall by guessing
the right database first — an extra round trip the local stack does not need.

### Generated set (20 val queries, non-template)

| | shipped | Notion |
|---|---|---|
| source note in top 10 | 19 / 20 (0.95) | 12 / 20 (0.60) |
| MRR@10 | 0.617 | 0.307 |
| found by both / shipped only / Notion only / neither | 12 / 7 / 0 / 1 |

| query | shipped rank | Notion rank |
|---|---|---|
| notes on humility and growth opportunities | 4 | — |
| notes about Anthropic Applied AI Engineer | 2 | 2 |
| what are the four steps of the structured thinking process | 3 | — |
| ethics and alignment in language modelling | 1 | 2 |
| where did I write about the problem-solving framework | 1 | 3 |
| where do I write about the linear model | 1 | 4 |
| What was the false positive rate target for the noise content project? | 2 | 6 |
| audio transformer trained on 20 million hours supervised | 1 | 1 |
| notes about daily communication practice | 10 | — |
| What makes a product delightful for children? | 4 | 5 |
| note about seeing it all and Revolut product owner | 2 | 2 |
| what did Warren Buffett learn from Benjamin Graham? | 1 | — |
| what word count does Anthropic expect for the application response | 1 | 1 |
| chris sacca urgent about everything | 1 | 2 |
| notes on uk ai infrastructure plan | 1 | — |
| notes about innovation and job focusing | — | — |
| how to name your mind to separate from it | 1 | — |
| notes on curated training plans user feedback | 2 | — |
| founders and coders workshop | 4 | 1 |
| how to de-risk startup hanging around right people | 6 | 5 |

Every note Notion missed here has a title that shares no word with the query
(*Chamath Palihapitiya*, *How warren learns*, *New Habits*, *Mo Gawdat Solve
for happy*, *AI Opportunities Action Plan*, *Bloom October 2025 Quarterly*).

## What Notion MCP would add

Each item was exercised in this session, not read from a brochure.

1. **Live data.** The export's newest note is dated 2026-08-09; the workspace
   has pages edited on 2026-09-03. The judged query "what tasks did I put down
   on August 20, 2026" is unanswerable from the export (`retrieval_improvements.md`,
   A5) but *Daily Check In @August 20, 2026* exists in Notion. The database
   the export calls *Document Hub* has since been renamed *Task Management*.
2. **Structured queries over databases.** `query-data-sources` exposes each
   Notion database as a SQLite table. One query,
   `SELECT url, Name FROM "collection://216d…" WHERE date("Created time") = '2026-08-01'`,
   returned exactly the *Daily Check In @August 1, 2026* page. Dates are the
   retrieval stack's known blind spot (B1): the lexical arm discards the year
   and the dense arms treat it as text. The Journal database carries `Tags`
   (Daily, Career, Life Lesson, …) and `Created`; the export flattened all of
   that into filenames. On this plan the tool is `available_with_limit` — a
   shared workspace quota for single-database SQL, unlimited only on Business
   or Enterprise with Notion AI.
3. **Metadata the export dropped.** `fetch` returns the ancestor path, last
   edited time, database properties, child-page links, comment threads and
   page mentions. None of this reaches a chunk today (B2). `search` results
   carry `path` and `timestamp`, which would let the agent disambiguate the
   *Document Hub* / *Document Hub (1)* twins that split credit today (A6).
4. **Whole pages in one call.** `fetch` returns a page as Notion-flavoured
   markdown with `truncated` / `unknown_block_ids` flags when a page is too
   large. The agent's "read the note behind this chunk" step becomes one MCP
   call instead of a filesystem read.
5. **Writes.** `create-pages`, `update-page`, `create-comment`. Saving an
   answer or a digest back into Notion becomes possible; nothing in sumi can
   write today.
6. **No ingest pipeline.** No Postgres, no two local embedding models to load
   (the dense arms each load a sentence-transformers model), no re-export
   ritual, no `chunks` table to keep stale.
7. **With Notion AI (not available here):** semantic search across the
   workspace and connected sources (Slack, Google Drive, …), unlimited SQL,
   multi-database SQL, title-only and last-edited filters.

## What would be lost

1. **Retrieval quality**, as measured above: about half the relevant notes,
   and six real queries that go from answered to unanswered.
2. **Chunk-level results.** The agent would receive titles and keyword
   highlights, then fetch whole pages. *Job Hunt 2025-2026* came back as over 30 KB
   of markdown in one fetch; today's `search_notes` returns at most ten
   2,000-character chunks. The history-stub mechanism in `src/tools/search.py`
   would need a page-level equivalent, and answer cost per query rises.
3. **Every tuning lever.** No arms, no fusion, no `rrf_k`, no reranker over
   50 candidates from three retrievers, no chunker, no embedding choice. The
   entire experiment table in `retrieval_overview.md` describes decisions that
   would no longer be sumi's to make.
4. **The evaluation harness as built.** `evals/retrieval/` joins results to
   judgments on `"{source}#{chunk_index}"`. Notion returns page ids. The
   graded chunk labels (ndcg, precision) cannot score a page-level retriever;
   only note-level metrics survive, via the filename-hash ↔ page-id mapping.
   The annotation UI (`src/annotation/`) pools chunks from retrievers; a Notion
   retriever would need a page-level pooling mode.
5. **Determinism and offline operation.** Rankings can change under sumi
   without a commit; a run recorded today may not reproduce next month.
   Nothing works without network and a valid token.
6. **Rate limits.** Notion documents an average of 180 requests per minute
   per user across all tools, with `search` capped at 30 per minute, plus a
   per-workspace limit scaled to plan. An eval run of 313 queries at one search
   per query needs ~11 minutes of wall clock at the search cap; the local
   harness is bounded by the embedding models instead.
7. **Plan dependence.** The useful search is behind Notion AI; SQL is quota'd
   on this plan. Retrieval quality would depend on a subscription.
8. **Sources outside Notion.** `data/mem-export` holds 1,073 files from a
   second notes app. It is not ingested today, but a local index could take it;
   Notion MCP never will.

## Integration facts (if any option below is built)

- Endpoint `https://mcp.notion.com/mcp` (streamable HTTP; `/sse` fallback).
  OAuth 2.0 with PKCE and dynamic client registration. Access tokens last
  about eight hours; refresh tokens rotate on every use and expire after 180
  days, or 30 days idle. No static integration token is offered for the hosted
  server.
- The installed `mcp` SDK (≥2.1.1) ships `mcp.client.auth.OAuthClientProvider`
  and a `TokenStorage` interface, so the OAuth dance is SDK work plus a token
  store under `secrets/` and a local redirect listener. `src/mcp_client.py`
  takes a `get_token` callable today; it would need to accept an httpx auth
  object instead. Whether Notion accepts a `http://localhost` redirect for a
  CLI was not verified.
- `fetch("self")` returns a `current_tool_access` map. For this workspace:
  `search`, `fetch`, all write tools and `list_*` are `available`;
  `query_data_sources` is `available_with_limit`; `query_multiple_data_sources`
  needs the full version; meeting-notes and Custom Agent tools need a plan.
- The open-source `makenotion/notion-mcp-server` wraps the public REST API,
  whose `search` endpoint matches **titles only**. It is not a substitute for
  the hosted server's content search.
- The REST API allows about three requests per second per integration and is
  the natural path for a **sync**: list pages (paginated), read blocks, filter
  by `last_edited_time` for incremental updates. A full pull of 2,329 pages is
  a matter of minutes at that rate.
- The REST API can also return a whole page as markdown in one request
  (`GET /v1/pages/{id}/markdown`, added 2026-02-26), so reading a page's
  blocks one level at a time is no longer the only REST path to its text —
  which is why the sync design needs no block-tree renderer.

## Options

| | A. Replace retrieval with Notion `search` | B. Sync the corpus from Notion, keep pgvector | C. Keep retrieval, add Notion tools |
|---|---|---|---|
| Retrieval quality | Halves today; unknown with Notion AI | Unchanged | Unchanged |
| Freshness | Live | As fresh as the last sync (cron) | Live for `fetch` and SQL; retrieval as fresh as the export |
| Dates, tags, path | Yes, via SQL and `fetch` | Yes, if stored as chunk metadata at sync time (B1, B2 become possible) | Yes, via SQL and `fetch` |
| Writes | Yes | No | Yes |
| Eval harness | Note-level only; chunk judgments unusable | Intact if `source` stays stable; chunk ids change where text changed | Intact; new tools unmeasured like Gmail |
| New moving parts | OAuth + token store | OAuth or REST token, sync job, id migration | OAuth + token store, allowlist |
| Plan dependence | High (Notion AI) | Low (REST API is on every plan) | Medium (SQL quota) |

**Recommendation: C now, B next, A not without Notion AI and a re-measurement.**

C is the Gmail pattern already in the codebase: an allowlist (`fetch`,
`query-data-sources`, perhaps `get-comments`; not `search`, which the numbers
above rule out as a retriever), a config field, one `register_mcp_tools` call. It gives the agent live page
reads and database SQL on day one and loses nothing. Its cost is the OAuth
plumbing, which B needs too.

B is what actually answers "the export is stale" without touching retrieval
quality. Sync from Notion into the same tables, keyed by page id rather than
filename, and store path, created time and tags as chunk metadata — turning
B1 and B2 from "possible next steps" into data that exists. The invariant to
protect is chunk ids: judgments join on them, so the migration must either
keep `source` as the export-style path or remap `data/annotations.json` once,
then pass `evals.retrieval.selftest`. The collected design notes for this
option are in `docs/plans/active/notion-sync.md`, and the design they became
is `docs/designs/notion-sync.md`.

A should be revisited only if the workspace gains Notion AI. The method in
this document (same queries, note-level, page-id mapping) is enough to score
it; expect to run it under the 30-searches-per-minute cap.

## Reproduction

`data/investigations/notion-mcp-2026-09-03/` (gitignored, local) holds
`notion_judged_results.json` (top-10 page ids per judged query),
`notion_gen_ranks.json` (rank of the source page per generated query),
`gen_sample.json` (the 20 sampled queries) and `compare.py`, which recomputes
every number above from those files and the shipped run's `per_query.json`.
