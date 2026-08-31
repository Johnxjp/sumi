# Candidate Retrieval: Build, Measure, Optimise

## Context

Sumi needs its candidate-retrieval stage built and tuned: a user query returns the top-k most relevant note chunks (generation is out of scope). The retrieval primitives already exist — `QwenEmbedder`/`BgeM3Embedder`, `PgVectorIndexer` over `chunks_qwen`/`chunks_bge_m3` (5979 rows each, **identical chunking and ids** `"{source}#{i}"`, all 2329 notes) — but there is **no evaluation code anywhere**, and no user-facing retrieval entry point.

Goal: build an NDCG@10-driven eval harness with a **train/val split** and diagnosis tooling, measure baselines, then let the implementer **experiment freely** — each next experiment chosen from diagnostics, not a fixed schedule — and ship the winning config behind `retrieve(query, top_k)` + a CLI. Levers in scope: embedder choice, fusion of qwen+bge-m3, a lexical/FTS arm, metadata (titles, source paths), depth/top_k/fusion params. **Out of scope: cross-encoder rerankers; chunking is fixed.**

**Ground truth (two query sets, combined then split):**
- `../data/annotations.json` — 19 human queries, 171 graded judgments (0/1/2), pooled from qwen+bge-m3 top-10. 2 queries have zero positives → excluded from NDCG aggregates but still run (results feed the unjudged queue). Join to results via `sources[].chunk_id` (matches table ids), fallback `compute_chunk_key(text)` (`src/annotation/pooling.py`).
- `../data/datasets/queries.json` — `{"queries": [...]}`, 294 LLM-generated `{source_file, query, passage}`; file-level binary relevance only. Strip prefix `../data/notion-export-markdown/` to match chunk `source`. Supports file-recall@10 / file-MRR@10 (pooling-bias-free), not graded NDCG.

**Fixed decisions (user-confirmed):** NDCG@10 primary; precision@10 guardrail; unjudged = not relevant but queued to a file for later human labeling (never block); train/val split of the combined dataset; deliverable = module + small CLI. Stale `chunks` table (gemini, different chunking) is never used.

## Metric definitions

- Gain scheme: exponential `2^rel − 1` → {0, 1, 3} (rewards putting highly-relevant chunks on top; recorded in each run's config).
- `NDCG@k = DCG@k / IDCG@k`, `DCG@k = Σ gain_i / log2(i+2)` (0-based rank). IDCG from **all** judged positives for the query, not just retrieved ones.
- Also: NDCG@5, recall@10 (judged positives found / all judged positives), MRR@10, precision@10 (judged positives in top-10 / 10), `judged_coverage@10` (fraction of top-10 that is judged — the unjudged-bias gauge), file-recall@10 / file-MRR@10 on the generated set.

## Phase 1 — Eval harness (`evals/retrieval/` package, pure Python first)

New package `evals/retrieval/` (with `__init__.py`; run via `python -m` from repo root; absolute imports). Reuse `normalize_query` (`src/annotation/store.py`) and `compute_chunk_key` (`src/annotation/pooling.py`) — do not reimplement.

- **`qrels.py`** — `GradedQuery{query_text, gain_by_chunk_id, gain_by_chunk_key, num_relevant}`; `load_graded_qrels(path) -> dict[normalized_query, GradedQuery]` (collect **every** `sources[].chunk_id` per annotation); `lookup_gain(qrel, row) -> int | None` (chunk_id hit → chunk_key fallback → `None` = unjudged); `FileQuery{query, source}`; `load_file_queries(path)` (reads the nested `"queries"` key, strips path prefix).
- **`metrics.py`** — pure functions, stdlib only (`math.log2`): `apply_gain`, `compute_dcg`, `compute_ndcg`, `compute_recall`, `compute_mrr`, `compute_precision`, all taking per-rank gain lists + k.
- **`split.py` + `make_split.py`** — one-time generated, committed-to-data split file `../data/datasets/split.json`: `{"seed": <int>, "train": [<normalized query>...], "val": [...]}`. `make_split.py` combines both datasets and splits **70/30, stratified by dataset kind** (annotated → ~13 train / 6 val; generated → ~206/88) with a fixed seed; refuses to overwrite an existing file without `--force` (a changed split invalidates all run comparisons). `split.py`: `load_split(path) -> Split{train: set, val: set}`.
- **`queue.py`** — `append_unjudged(queue_path, qrels, run_id, entries) -> int` writing `../data/unjudged_queue.json`: dict keyed `"<normalized_query>||<chunk_id>"` → `{query, chunk_id, chunk_key, text, source, title, best_rank, runs, first_seen_at}`. Dedup across runs (update `best_rank`=min, append run_id), skip anything now judged, atomic write (copy tempfile+`os.replace` pattern from `store.py`). Annotated queries only — not the 294 generated.
- **`runner.py`** — `ExperimentConfig{name, retrieval: RetrievalConfig, gain_scheme, notes}`; `async run_experiment(config, ...) -> dict`. Build arms **once** per run (model load ~15s); per query: gather per-arm results at `depth`, fuse/passthrough, truncate to top_k=10, score. **Always runs all queries; metrics are aggregated separately for train and val** (each with an `annotated` sub-block — ndcg@10/ndcg@5/recall@10/mrr@10/precision@10/judged_coverage@10/num_queries/excluded_zero_positive — and a `generated` sub-block — file_recall@10/file_mrr@10). Persist to `../data/eval_runs/<run_id>/` (`mkdir(parents=True, exist_ok=True)`): `config.json`, `metrics.json`, `per_query.json` (per-query metrics + ranked results with gain/judged flags + `split` tag + per-arm provenance). `run_id = "<UTC timestamp>-<name>"`.
- **`experiments.py`** — registry `EXPERIMENTS: dict[str, ExperimentConfig]`. Populated as experimentation proceeds (not pre-specified); every run is declared here so any result is reproducible by name, with keep/drop rationale in `notes`.
- **`run.py`** — CLI `uv run python -m evals.retrieval.run <experiment-name> [--annotated-only]` (fast-iteration flag skips the 294 generated queries).
- **`compare.py`** — CLI reading all `../data/eval_runs/*/metrics.json`; table sorted by train ndcg@10 with train and val columns side by side.
- **`diagnose.py`** — the "why did it change" tool:
  - `uv run python -m evals.retrieval.diagnose <run_id>` — per-query table: metric values, judged_coverage, ranks at which each known positive appeared (or "missed"), and which arm(s) contributed each top-10 chunk. Sorted worst-first so failure patterns (e.g. date queries, entity queries) jump out.
  - `uv run python -m evals.retrieval.diagnose <run_a> <run_b>` — per-query deltas sorted by change, with the top-10 diff (chunks gained/lost, rank moves) for the biggest movers. This is what drives the choice of the next experiment.

## Phase 2 — Production retrieval pieces (`src/retrieval/`)

- **`search_config.py`** — plain Python (mirror `src/annotation/config.py`; **never** touch `src/config.py` — `extra="forbid"` means new env vars break all imports of `app_config`):
  ```python
  @dataclass(frozen=True)
  class ArmConfig:
      name
      kind: Literal["dense", "lexical"]
      table
      embedder: str | None = None
      depth: int = 50


  @dataclass(frozen=True)
  class RetrievalConfig:
      arms: tuple[ArmConfig, ...]
      fusion: Literal["single", "rrf"] = "single"
      rrf_k: int = 60
      weights: tuple[tuple[str, float], ...] | None = None
      top_k: int = 10


  ACTIVE_CONFIG = RetrievalConfig(
      ...
  )  # best baseline initially; set to winner at the end
  ```
- **`fusion.py`** — `fuse_rrf(ranked: dict[arm, list[row]], k=60, weights=None) -> list[row]`: score `Σ weight/(k + rank)` (rank from 1), **dedup by `row["id"]`** (safe: all tables share ids by construction — note in docstring), keep first-seen text/source/metadata, replace `score` with RRF score, attach `"arms": {arm: rank}` provenance (feeds `diagnose.py`), sort `(-score, id)`. Single-arm configs bypass fusion.
- **`lexical.py`** — `PgFtsIndexer(database_url, table="chunks_fts")` matching the `Indexer` search contract (`{"id","text","source","metadata","score"}` — pooling/fusion/queue code shared unchanged). Standalone table (one text copy, rebuildable independently of embeddings):
  ```sql
  CREATE TABLE IF NOT EXISTS chunks_fts (
    id text PRIMARY KEY, text text NOT NULL, source text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}',
    tsv tsvector GENERATED ALWAYS AS (
      setweight(to_tsvector('english', coalesce(metadata->>'title','')), 'A') ||
      setweight(to_tsvector('english', text), 'B')) STORED);
  CREATE INDEX IF NOT EXISTS chunks_fts_tsv_idx ON chunks_fts USING GIN (tsv);
  ```
  `sync_from("chunks_qwen")` = idempotent `INSERT ... SELECT ... ON CONFLICT (id) DO UPDATE`. Search: `websearch_to_tsquery('english', %s)` + `ts_rank_cd(tsv, q)`, `ORDER BY score DESC, id LIMIT %s` (stopword-only query → `[]`, correct). `index()` raises NotImplementedError. New script `scripts/build_fts.py` (`ensure_schema` + `sync_from` + print count). A weight-C component over the cleaned `source` path (strip 32-hex ids and `/.` via `regexp_replace`) is an available variant if diagnostics suggest folder names matter.
- **`retrieve.py`** — `HybridRetriever(config, database_url=None)` (defaults `app_config.database_url`; builds arm indexers once) with `async retrieve(query, top_k=None)`; `build_arm_indexer(arm, database_url) -> Indexer` enforcing embedder↔table pairing (`chunks_qwen*` only with `QwenEmbedder` — it has a query prompt; `chunks_bge_m3` only with `BgeM3Embedder`); module-level `@lru_cache` `get_default_retriever()` + thin `async retrieve(query, top_k=10)` (cache justified: avoids reloading models per call).
- **`TitlePrefixEmbedder(inner)`** in `embedder.py` — available metadata lever: `SentenceTransformerEmbedder` embeds documents verbatim (titles ignored — confirmed, `embedder.py:256`). Wrapper duck-types `Embedder`: documents embed as `"{title}\n\n{text}"`, queries pass through; `--title-prefix` flag on `scripts/ingest.py` appends `_title` to the table name. **Invariant:** `Document.text` stays the raw chunk — only the embedded string is prefixed — so ids/stored text and the qrels join are unchanged.
- **Bug fix in `indexer.py` (required before any depth>40 arm):** `PgVectorIndexer.search` never sets `hnsw.ef_search` (pgvector default 40), so HNSW scans silently cap at ~40 rows. Execute `SET hnsw.ef_search = %s` (`max(top_k, 40)`) on the connection before the select (verified missing at `src/retrieval/indexer.py:207`).
- Optional (~8 lines, recommended): `type == "fts"` branch in `src/annotation/retrievers.build_retriever` + an fts entry in `src/annotation/config.py`, so queued FTS-surfaced chunks actually appear in the annotation UI when the user labels later.

## Phase 3 — Baselines, then results-driven experimentation

1. **Generate the split once** (`make_split.py`), commit `split.json` alongside the datasets.
2. **Baselines:** `baseline-qwen` and `baseline-bge-m3` (single arm, depth 10). Harness self-test: their annotated `judged_coverage@10` must be ≈ 1.0 (the annotation pool came from exactly these arms at top-10) — if not, the qrels join is broken; stop and fix before experimenting.
3. **Experiment loop — implementer's free rein.** No pre-set schedule: after each run, use `diagnose.py` (worst queries, per-arm provenance, run-vs-run deltas) to pick the next change. The lever menu: qwen vs bge-m3, RRF fusion of the two, adding the FTS arm, fusion weights, `depth`/`rrf_k`/`top_k`, title-prefixed embeddings, title/source-path weighting in FTS. One config change per run; register every run in `experiments.py` with its keep/drop rationale.

**Decision rule (identical every run):** optimise on **train** — keep a change iff train annotated NDCG@10 beats the current best. Guardrails on train: precision@10 within 0.02 absolute of the best baseline; generated file-recall@10 / file-MRR@10 must not materially regress (they're pooling-bias-free; use file-MRR@10 as tiebreaker when |ΔNDCG@10| < 0.01 — 13 annotated train queries is noisy). **Val is the honesty check, not an optimisation target:** consult it only for kept changes; the final winner must beat the baseline on val too (or at minimum not regress) — if train and val disagree, the train gain is overfit and the change is dropped. If `judged_coverage@10 < ~0.8`, flag that run's NDCG as a lower bound in its `notes`; queue unjudged pairs and move on — never block on labeling.

## Phase 4 — Final deliverable

Set `ACTIVE_CONFIG` to the winner in `search_config.py`. `scripts/search.py`: `uv run python -m scripts.search "query" [--top-k 10]` → argparse → `asyncio.run(retrieve(...))` → print `rank. score  source  (title)` + ~200-char snippet.

## Tests (100% of new behaviour, no more — per AGENTS.md)

Unit (pure, parametrized, hand-computed expectations):
- `tests/test_eval_metrics.py` — e.g. gains `[3,0,1]` vs judged `{3,1}` → NDCG@10 ≈ 0.925; perfect → 1.0; empty → 0.0; @5 vs @10 truncation; recall denominator = all judged positives; MRR; precision; gain mapping (0,1,2)→(0,1,3).
- `tests/test_qrels.py` — tmp_path fixtures: normalized keying; all `sources[].chunk_id` collected; `lookup_gain` id-hit / chunk_key-fallback (whitespace-variant text) / unjudged→None; `load_file_queries` nested key + prefix strip.
- `tests/test_split.py` — stratified proportions per dataset kind, determinism for a fixed seed, train/val disjoint and exhaustive, refuse-overwrite behaviour.
- `tests/test_fusion.py` — hand-computed `1/(60+r)` sums; dedup-by-id merges contributions + provenance; weights; deterministic tie-break; empty/single arm.
- `tests/test_unjudged_queue.py` — cross-run dedup, `best_rank` min-update, judged entries skipped, count = new items only, round-trip.
- `tests/test_retrieve.py` — `HybridRetriever` with autospec-mocked arms (single-arm bypasses fusion; multi-arm fuses + truncates); `build_arm_indexer` pairing enforcement + error cases.
- `tests/test_embedder.py` additions — `TitlePrefixEmbedder` prefixes documents, passes queries through (autospec inner).
- Runner: unit-test pure helpers only (train/val aggregation, zero-positive exclusion, `persist_run` to tmp_path) with a fake retriever; `diagnose.py`'s delta/provenance helpers as pure functions over `per_query.json` fixtures.

DB-gated (copy `_postgres_available()` + skipif + `sumi_test` fixture from `tests/test_pg_indexer.py`; never the real DB):
- `tests/test_fts_indexer.py` — schema idempotent; result-row shape/order; title-hit (A) outranks body-hit (B); stopword-only → `[]`; top_k; quoted phrase.
- `tests/test_pg_indexer.py` addition — ~60 docs, `search(top_k=60)` returns 60 rows (fails without ef_search fix).

## Verification

1. `uv run ruff check . --fix && uv run ruff format .` after every file; `uv run pytest` green (DB tests run — Postgres is up).
2. Harness self-test (Phase 3 step 2) passes on both baselines.
3. Spot-check: run `uv run python -m scripts.search "what does napoleon say about leadership"` and eyeball that known-relevant chunks (e.g. `Journal/Take responsibility ….md#0`) rank sensibly; compare 2–3 queries' `per_query.json` against annotations by hand.
4. `uv run python -m evals.retrieval.compare` shows all runs (train + val); final report to user: baseline vs winner on train **and** val, the experiment log with keep/drop rationale, worst remaining queries from `diagnose.py`, and the size of the unjudged queue awaiting their labels.

## Gotchas

- Unjudged bias: FTS/title/deep arms are scored pessimistically — treat their NDCG as a lower bound; the generated-set file metrics are the bias-free cross-check; the queue → annotation UI → optional re-run closes the loop later.
- Tiny annotated val split (~6 queries): val NDCG is directional only — use it to catch gross overfitting, never to pick between close configs.
- Zero-positive queries: excluded from aggregates, still retrieved (prime candidates to gain positives from the lexical arm).
- No new env vars anywhere (`extra="forbid"`); all knobs in dataclasses/argparse.
- Never touch stale `chunks` table. Fusion dedup relies on shared ids across tables — holds by construction; documented in `fusion.py`.
- `ts_rank_cd` ordering isn't index-accelerated — fine at 6k rows, don't optimise.
