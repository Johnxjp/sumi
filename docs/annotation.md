# Annotation tool

The labelling UI that produces the human relevance judgments the retrieval
evals score against. Code: `sumi-backend/src/annotation/` (FastAPI) and
`sumi-backend/static/` (one vanilla-JS page). Run from `sumi-backend/`:

```
uv run uvicorn src.annotation.app:app --reload --port 8765   # → http://localhost:8765
```

## What happens when you label a query

1. You type a query. `POST /api/search` sends it to every retriever declared
   in `src/annotation/config.py` — today Qwen (`chunks_qwen`), BGE-M3
   (`chunks_bge_m3`) and the lexical index (`chunks_fts`) — and takes each
   one's top results.
2. The results are **pooled**: merged into one list and deduplicated by a hash
   of whitespace-normalised chunk text (`pooling.py`), so a chunk several
   retrievers return is graded once. Each pooled chunk keeps the rank and
   score every retriever gave it.
3. You grade each chunk **blind** — the page never shows which retriever
   returned it, so no system can be favoured: 2 = highly relevant,
   1 = partially relevant, 0 = not relevant.
4. `POST /api/annotations` writes the grades to `data/annotations.json`
   (atomic write, `store.py`), keyed by case- and whitespace-normalised query
   text. Re-running a query pre-fills its existing grades, so labelling is
   incremental.

Judgments attach to chunk text, not to a retriever, so one labelled query
scores every current retriever and any future one — with the usual caveat
that a new retriever may surface chunks nobody has graded yet.

## Retriever types

`retrievers.py` builds a retriever from each `RetrieverConfig`:

| type | needs | what it is |
|---|---|---|
| `pgvector` | `embedder`, `table` | a dense arm over one of the pgvector tables |
| `fts` | `table` | the lexical arm over `chunks_fts` |
| `static` | `chunks_file` | a fixed result list from a JSON file |
| `breadbowl` | `index_id`, `BREADBOWL_API_URL`/`_KEY` in the environment | the legacy external index |

Adding a retriever to the pool is one line in `config.py`. A retriever's
`search()` may be sync or async; the endpoint awaits when it has to.

## How the judgments are used

`sumi-backend/evals/retrieval/qrels.py` reads `annotations.json` into graded
relevance sets. A chunk a run returns is joined to its grade by chunk id (ids
are identical in every table) with a text-hash fallback for retrievers whose
ids differ. `evals/retrieval/selftest.py` checks that join before any number
is trusted.

The pool was graded from the top down and not to the bottom, so a run often
returns chunks that have no grade. Those are scored as irrelevant and
collected in `data/unjudged_queue.json`. **The UI does not read that file
yet** — to grade a queued chunk, re-run its query here; the pool now includes
the lexical arm, so the chunk will surface.

## Current state

- 19 real queries labelled, 171 judgments. What that is and isn't enough for:
  `docs/retrieval/retrieval_overview.md` (datasets) and
  `docs/retrieval/retrieval_improvements.md` (A1, A2, A5).
- The synthetic query set (`evals/generate_queries.py`) does not go through
  this tool; its ground truth is the note each query was generated from.
