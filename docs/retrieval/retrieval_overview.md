# Retrieval System Overview

How sumi finds the right chunks of your Notion notes for a query: what it
scores today, how it is built, what data it is measured on, how it is measured,
and how the current design was chosen. Paths are relative to `sumi-backend/`
unless noted; data lives in `data/` (gitignored). Last updated 2026-09-01.

Terms used throughout, in plain words:

- **Chunk** — a piece of a note, at most 2,000 characters. Retrieval returns
  chunks, not whole notes.
- **Arm** — one independent search method. The shipped system runs three arms
  and merges their results.
- **Judgment / label** — a human score (0, 1 or 2) saying how relevant a chunk
  is to a query.
- **Train / val** — the queries used to *choose* a configuration (train) and
  the held-out queries used to *check* the choice wasn't a fluke (val).

## Current performance

Shipped configuration: `rrf-3arm-k5` (run `20260901T080825Z-rrf-3arm-k5`).
Numbers are means over queries; higher is better; all are computed on the top
10 results.

| metric | what it measures | train | val |
|---|---|---|---|
| ndcg@10 | ranking quality on human-judged queries (primary) | **0.712** | **0.825** |
| ndcg@10_condensed | same, ignoring never-judged chunks | 0.731 | 0.837 |
| precision@10 | share of the top 10 judged relevant | 0.233 | 0.520 |
| file_recall@10 | generated queries whose source note appears in the top 10 | **0.710** | 0.747 |
| file_mrr@10 | how high that source note appears (1 = first) | 0.548 | 0.552 |
| judged queries | | 12 | 5 |
| generated queries | | 203 | 87 |

For comparison, the best single arm scored train ndcg@10 **0.567** (Qwen and
BGE-M3 tie), file_recall@10 0.580 (Qwen); the lexical arm alone scored 0.236.
The full run table is under *Experimentation* below.

Two things to keep in mind when reading these numbers:

- **They are a floor, not an estimate.** 39% of the chunks in the winner's
  top 10 for judged queries have never been labelled (116 of 190 judged) and
  are counted as irrelevant. Labelling them can only raise the scores.
- **The judged set is small.** 12 train queries decide the primary metric and
  5 decide val. Differences between configurations are corroborated across
  several metrics, not statistically significant. See
  `retrieval_improvements.md`.

## What the system does

Sumi is a RAG system over a personal Notion export: 2,329 markdown notes,
split into 5,979 chunks, stored in Postgres. Given a query, `retrieve(query,
top_k=10)` (`src/retrieval/retrieve.py`) returns the ten chunks most likely
to answer it. This document covers that retrieval step only, not answer
generation. The agent REPL (`main.py`) does not use this stack yet; it still
reads the notes directory with filesystem tools.

## Architecture

### Ingestion

`scripts/ingest.py` walks the notes directory and, per file:

1. **Clean** (`src/retrieval/cleaner.py`): unicode normalisation, whitespace
   and control-character cleanup.
2. **Chunk** (`src/retrieval/chunker.py`): recursive splitter, 2,000-char max,
   200-char min, 50-char overlap, breaking on paragraph → line → sentence →
   word boundaries.
3. **Embed and store**: each chunk is embedded and upserted into one table per
   embedding model. Chunk ids are `"{source}#{chunk_index}"`, so the same id
   means the same chunk in every table. This is what lets the merge step
   recognise the same chunk coming from different arms.

The only metadata attached to a chunk is the note **title** (filename with the
Notion hash stripped). Folder path is stored as `source` but not searched.

### Three arms

| arm | table | how it searches |
|---|---|---|
| `qwen` | `chunks_qwen` | Qwen3-Embedding-0.6B (local, 1024-dim). Cosine similarity over pgvector with an HNSW index. Searches by *meaning*. |
| `bge-m3` | `chunks_bge_m3` | BAAI/bge-m3 (local, 1024-dim). Same mechanism, different model. |
| `fts` | `chunks_fts` | Postgres full-text search. Searches by *words*. |

Both dense arms embed the chunk body only; the title is not prepended (that
variant was measured and made no difference — see the experiment table). The
HNSW scan is told to visit at least as many candidates as are requested
(`SET hnsw.ef_search`), otherwise a deep search silently returns 40 rows.

The lexical arm (`src/retrieval/lexical.py`) is built by
`scripts/build_fts.py`, which copies text and title from `chunks_qwen` into
`chunks_fts`. Postgres reduces each chunk to word stems ("running" → "run",
filler words like "the" dropped), with title words weighted above body words.
At query time it:

1. Reduces the query to stems the same way.
2. Counts how many chunks contain each stem.
3. Drops stems present in more than 15% of chunks (`max_df=0.15`) — words
   like "make", "people", "say" that cannot tell chunks apart. If every stem is
   that common, all are kept rather than returning nothing.
4. Matches any chunk containing at least one surviving stem (OR, not AND —
   requiring every word returns nothing for question-shaped queries).
5. Scores each chunk by the summed rarity (IDF) of the query stems it
   contains, plus a 0–1 tie-breaker for how often and how close together the
   words occur.

Without the rarity weighting, a chunk repeating a common word outranks the
one chunk mentioning a rare name; without the common-word cut, the slowest
query took 2,100 ms instead of 24 ms.

### Fusion

Each arm returns its top 50. `fuse_rrf` (`src/retrieval/fusion.py`) merges
them with reciprocal rank fusion: a chunk scores `1 / (5 + rank)` from every
arm list it appears in, the scores are summed, and the top 10 by total are
returned. `rrf_k=5` (the usual default is 60) is what makes a single arm's
rank-1 hit outweigh two arms agreeing at rank 40. Arms have equal weight.
Every returned row records which arm ranked it where, under `"arms"`.

On the judged queries, of the winner's 190 top-10 slots: 70 came from all
three arms, 84 from two, and 36 from a single arm (18 lexical only, 11 BGE
only, 7 Qwen only). Each arm contributes results the others miss.

The declarative config is `src/retrieval/search_config.py:ACTIVE_CONFIG`.

```
query ──┬── qwen  (top 50) ──┐
        ├── bge-m3 (top 50) ─┼── RRF, k=5 ── top 10
        └── fts   (top 50) ──┘
```

## Datasets

### Corpus

2,329 `.md`/`.txt` files from the Notion export (`data/notion-export-markdown`),
5,979 chunks. About a quarter of the notes are recurring templates (Daily
Check In, End of week check in, Plan for the week); this matters for the
generated set below.

### Judged set (19 queries, 171 judgments)

Real queries typed by the note owner, labelled in the annotation tool
(`src/annotation/`). For each query the tool pools the top results of every
declared retriever (Qwen, BGE-M3 and, since the last PR, the lexical arm),
deduplicates them by chunk text, and shows them **blind** — the labeller never
sees which retriever returned a chunk. Each chunk gets 0 (not relevant),
1 (partially) or 2 (highly relevant). Labels are stored in
`data/annotations.json`, keyed by normalised query text, with per-retriever
rank provenance kept for each chunk.

Between 5 and 19 chunks were labelled per query. Relevant chunks per query:
`0, 0, 1, 1, 2, 2, 2, 2, 2, 2, 3, 4, 4, 4, 5, 6, 7, 8, 10`. The two queries
with no relevant chunk are excluded from scoring, leaving 17 (12 train,
5 val).

### Generated set (294 queries)

`evals/generate_notes_sample.py` samples 100 notes of at least 250
characters; `evals/generate_queries.py` asks an LLM
(`nvidia/nemotron-3.5-lightning:free`, temperature 0.7, prompt in
`evals/prompts/system_prompt_queries.md`) for three queries per note, each
with the passage that supports it. The prompt simulates the owner searching
months later without the note in front of them and asks for four query types
(LOCATE / FACT / TOPIC / VAGUE); the type is not saved, so no per-type
breakdown exists yet. Output: `data/datasets/queries.json` (294 queries,
290 unique after normalisation).

Ground truth is the **source note**: a result counts as a hit if it is any
chunk of the note the query was generated from. No human labelling needed,
and — unlike the judged set — no dependence on which retrievers built a pool,
so these metrics are free of pooling bias.

### Train / val split

`evals/retrieval/make_split.py` (seed 17) assigns 70% of each set to train
and 30% to val, independently per set: 13/6 judged queries, 203/87 generated.
Stored in `data/datasets/split.json`. Configurations are chosen on train and
confirmed on val. The split is never regenerated: every recorded run was
scored on the same queries, and changing it would make them incomparable.

## Evaluation metrics

All computed by `evals/retrieval/runner.py` over the top 10 (`K = 10`).

**On the judged set** (relevance grades 0/1/2 mapped to gains 0/1/3, so a
highly-relevant chunk near the top outweighs several partial ones):

- **ndcg@10 — primary.** "Normalised discounted cumulative gain": credit for
  each relevant chunk, discounted the further down it appears, divided by the
  credit a perfect ordering would get. 1.0 = every judged positive at the top
  in the right order. It uses the graded labels directly and rewards ordering,
  which is why it is primary. The ideal ordering includes positives the run
  did not retrieve, so missing one is penalised.
- **ndcg@10_condensed.** The same, but never-judged chunks are removed from the
  ranking instead of counted as irrelevant. It shows how much of the primary
  number is the pool's incompleteness rather than the retriever. It did not
  reorder the leaderboard.
- **precision@10.** Fraction of the top 10 with a positive label.
- **recall@10.** Fraction of the query's positives found in the top 10.
- **mrr@10.** 1 / rank of the first positive.
- **ndcg@5.** ndcg over the top 5.
- **judged_coverage@10.** Fraction of the top 10 that has *any* label. Not a
  quality metric; it says how trustworthy the others are (0.61 for the
  winner).

**On the generated set:**

- **file_recall@10.** 1 if any chunk of the source note is in the top 10,
  else 0.
- **file_mrr@10.** 1 / rank of the first such chunk.

A configuration is judged primarily on train ndcg@10; train file_recall@10,
val ndcg@10 and val file_recall@10 must agree in direction before a change is
kept.

**Unjudged results.** A chunk a run surfaces that nobody has labelled scores
0 but never blocks a run: it is appended to `data/unjudged_queue.json`
(currently 399 query–chunk pairs, 90 of them seen at rank ≤ 3). The
annotation UI does not read that file yet; re-running the query there
surfaces the same chunks for grading.

**Self-test.** `uv run python -m evals.retrieval.selftest` re-runs the arm the
annotation pool was built from and checks that every label it contributed at
rank ≤ 10 (111 of them) is found again by the label lookup. If this fails,
every score in every run is wrong. Run it before trusting a new number.

## Experimentation methodology

The loop, all under `evals/retrieval/`:

1. **Register** a configuration by name in `experiments.py`, changing one
   lever at a time (arms, depth, `rrf_k`, weights, embedding variant).
2. **Run** it: `uv run python -m evals.retrieval.run <name>`. Every run writes
   `config.json`, `metrics.json` and `per_query.json` (every result, its
   label, and which arms returned it) to `data/eval_runs/<timestamp>-<name>/`.
3. **Compare**: `uv run python -m evals.retrieval.compare` prints every
   recorded run, train and val side by side.
4. **Diagnose**: `uv run python -m evals.retrieval.diagnose <run> [<other>]`
   lists the worst queries, where each positive landed, and per-query deltas
   between two runs — this is what explained *why* `rrf_k` mattered.
5. **Record the verdict** in the registry entry's `notes` (kept or dropped,
   and the number), so the log lives next to the config that produced it and
   any run can be reproduced by name.

There is no pre-planned schedule of experiments: each result picks the next
lever. The sweep that produced the shipped configuration, in order:

| configuration | train ndcg@10 | train file_recall@10 | val ndcg@10 | verdict |
|---|---|---|---|---|
| baseline-qwen | 0.567 | 0.580 | 0.711 | baseline |
| baseline-bge-m3 | 0.567 | 0.570 | 0.945 | baseline; ties Qwen on mean, disagrees per query |
| baseline-fts | 0.236 | 0.609 | 0.439 | baseline; 78% of its top 10 unlabelled, best single-arm file recall |
| rrf-qwen-bge (k=60) | 0.535 | 0.594 | 0.867 | dropped — below either arm alone |
| rrf-qwen-bge-fts (k=60) | 0.579 | 0.647 | 0.775 | kept — beats every baseline |
| rrf-qwen-fts | 0.462 | 0.676 | 0.664 | dropping BGE costs 0.117 |
| rrf-bge-fts | 0.462 | 0.671 | 0.692 | dropping Qwen costs the same |
| rrf-3arm-d20 | 0.650 | 0.696 | 0.767 | kept, then superseded by rrf_k |
| rrf-3arm-d100 | 0.603 | 0.643 | 0.777 | dropped — deeper adds noise |
| rrf-3arm-k30 | 0.600 | 0.652 | 0.785 | on the monotone stretch |
| rrf-3arm-k10 | 0.656 | 0.696 | 0.814 | kept — first sign rrf_k is the lever |
| rrf-3arm-dense-heavy | 0.527 | 0.614 | 0.817 | dropped — lexical earns a full vote |
| rrf-3arm-lexical-heavy | 0.431 | 0.691 | 0.685 | dropped |
| rrf-3arm-k10-d20 | 0.664 | 0.705 | 0.789 | below k=5 at full depth |
| **rrf-3arm-k5** | **0.712** | **0.710** | **0.825** | **shipped** |
| rrf-3arm-k2 | 0.690 | 0.705 | 0.830 | past the optimum |
| rrf-3arm-k1 | 0.678 | 0.705 | 0.844 | confirms k=5 is a peak, not an edge |
| baseline-qwen-title | 0.574 | 0.575 | 0.735 | dropped — a wash for a full re-ingest |
| rrf-3arm-k10-title | 0.646 | 0.696 | 0.789 | dropped — below plain Qwen at k=10 |

The finding that mattered: `rrf_k`, not the choice of arms, moved the score.
At the conventional k=60 two arms agreeing far down their lists
(1/80 + 1/80) outvote one arm's rank-3 hit (1/63), so chunks a single arm
ranked highly fell out of the top 10. Lowering k to 5 restores them without
discarding candidates the way a shallower depth does.

## Commands

```
uv run python -m scripts.ingest --embedder qwen      # then bge-m3
uv run python -m scripts.build_fts                    # lexical index
uv run python -m scripts.search "your query"          # try it
uv run python -m evals.retrieval.selftest             # before trusting numbers
uv run python -m evals.retrieval.run <experiment>
uv run python -m evals.retrieval.compare
uv run python -m evals.retrieval.diagnose <run_id> [<other_run_id>]
uv run uvicorn src.annotation.app:app --reload --port 8765   # label queue
```
