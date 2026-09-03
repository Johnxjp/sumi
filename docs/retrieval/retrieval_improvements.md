# Retrieval: Failure Modes and Room for Improvement

Where the shipped retrieval configuration (`rrf-3arm-k5`, see
`retrieval_overview.md`) is known to be weak, with the evidence for each.
Every number below was reproduced from the data on 2026-09-01 unless marked
*as reported*, meaning it comes from the failure analysis of that date and was
not re-run. Sections are grouped by whether the problem is in how we
**measure** or in how we **retrieve**; the measurement problems come first
because they decide how much the retrieval numbers can be trusted.

Directions under "Possible next step" are options, not a plan. The working
rule is that results pick the next experiment.

---

## Part A — Measurement

### A1. Most of what the winner returns has never been labelled

**What happens.** Of the 190 chunks in the winner's top 10 across the judged
queries, 116 have a label and 74 do not. Unlabelled chunks are scored as
irrelevant. Every ndcg/precision/recall figure is therefore a floor, and the
gap between configurations is partly a gap in how much of each one's output
happened to be in the pool. The lexical arm alone illustrates the extreme: 78%
of its top 10 is unlabelled, so its 0.236 ndcg says almost nothing about it.

**Evidence.** `judged_coverage@10` = 0.61 for the winner; 0.22–0.66 across
configurations. `data/unjudged_queue.json` holds 399 query–chunk pairs, 90 of
them seen at rank ≤ 3.

**Possible next step.** Label the queue, highest `best_rank` first. This is
the single cheapest way to make every existing number more accurate, and it
should happen before further tuning. The annotation UI does not read the
queue file; either re-run each queued query there or add a queue view to it.

### A2. The judged set is too small to separate configurations

**What happens.** 12 train queries decide the primary metric and 5 decide
val. 10 of the 19 queries have two or fewer relevant chunks, so one chunk
moving in or out of the top 10 swings a query's ndcg by a large fraction. Val
ndcg disagrees with train on which single arm is best (BGE-M3 alone scores
0.945 on val, 0.567 on train) because 3 of the 5 val queries happen to be ones
it answers near-perfectly.

**Evidence.** Relevant chunks per query: `0, 0, 1, 1, 2, 2, 2, 2, 2, 2, 3, 4,
4, 4, 5, 6, 7, 8, 10`. The `rrf_k` result is trusted because train ndcg,
condensed ndcg, val ndcg and both file metrics moved the same way — that is
corroboration, not significance.

**Possible next step.** More real queries through the annotation tool. The
marginal value of a labelled query is far higher than of another
configuration run.

### A3. The generated set is contaminated by template notes

**What happens.** Scoring on the generated set treats "the source note is in
the top 10" as a hit. But 582 of the 2,329 notes are recurring templates
(Daily Check In, End of week check in, Plan for the week), and 66 of the 294
queries were generated from them. Their passages are often shared verbatim
with many other notes of the same template, so retrieving the "wrong" copy is
counted as a miss even when the text is identical. *As reported:* 56 of the
winner's 82 generated-set misses are template queries; excluding template
and prompt-leak queries lifts its file_recall@10 from 0.72 to 0.89.

**Evidence.** Counts above reproduced from `data/datasets/queries.json` and
the notes directory. The winner's 82 misses break down as: 42 whose passage
appears verbatim in at least one other note (up to 421 others), 14 more from
a template note whose passage was paraphrased so the sharing is unmeasured,
3 prompt-leak queries (A4), and 23 misses on a unique note whose passage is
present — the only ones that say anything about retrieval. Of those 23, 6
were in a single arm's top 10 and lost in fusion (B11), 4 are near-verbatim
lines that no arm matched (B5), and 2 are queries the passage does not
support (A4).

**Possible next step.** Either exclude template notes from sampling when the
set is regenerated, or score a generated query as a hit when *any* note whose
chunk text matches the passage is retrieved.

### A4. Other generated-set defects

- **Prompt leak.** 3 queries ask about the "fire of London" ("notes on fire
  of london", "what year was the great fire of london", "what was that fire
  which burnt london"), copied from the examples in the generation prompt and
  all attributed to the *Product Management Behavioural Questions* note. The
  phrase appears in no note. They are missed by every run.
- **Passages not verbatim.** 72 of 294 recorded passages do not appear
  verbatim in their source note, so the passage cannot be used as a
  chunk-level ground truth without fuzzy matching.
- **Passage does not support the query.** For some queries the recorded
  passage is not an answer: "what about the DeepMind link" → passage is the
  bare URL `https://deepmind.google/`; "notes on context engineering and big
  ideas" → passage is "Stop being so vague John. Start getting more precise…",
  which mentions neither. These cannot be retrieved by matching the query to
  the text.
- **Query type discarded.** The prompt asks for LOCATE / FACT / TOPIC / VAGUE
  queries and the model returns a `type` field, but the pydantic model in
  `evals/generate_queries.py` drops it. The per-type breakdown — the most
  likely place for arms to differ — cannot be produced.
- **Duplicates.** 294 queries, 290 unique after normalisation. Runs and the
  split are keyed by normalised query, so an exact duplicate generated from a
  different note shares its key with the first; the template prompt "what
  would I do if I knew I couldn't fail" appears five times in variants
  against four different notes.
- **Not yet built.** The generation script's docstring describes filtering
  too-easy queries and removing near-duplicates by embedding similarity;
  neither is implemented.

**Possible next step.** Check each passage against its note at generation
time and keep only verbatim ones. The 223 passages that are verbatim today
each fall inside exactly one chunk (the chunker never splits them), which
gives chunk-level ground truth for free: a chunk-recall@10 / chunk-MRR@10 on
the generated set would be free of the pooling bias in A1 and sharper than
the file-level metric.

### A5. Judged-set defects

- The query "What tasks did I put down on August 20, 2026" has no possible
  answer: the latest dated note in the export is August 9, 2026. It is one of
  the two zero-positive queries excluded from scoring, but it still consumes
  labelling effort.
- Two queries have no relevant chunk at all and are excluded, leaving 17
  scored.
- The other zero-positive query, "who were key people in the stoic
  philosophy", is borderline unanswerable: "stoic" appears in 5 notes, Marcus
  Aurelius in 1, Seneca in 2, Epictetus in none. None of those 5 notes was in
  the pool, so the query was judged only on generic "people I admire" lists
  and could not gain a positive. Either those notes get labelled or the query
  is dropped.
- **The pool is shallow and came from two of the three arms.** The first 5
  queries were judged on a top-5 pool (5 judgments each); the rest on top-10
  from Qwen and BGE-M3 only. Anything the lexical arm surfaces is unjudged by
  construction (A1). One consequence: for "summarise what's in my personal
  vision doc" only chunk #0 of the *Personal Vision* note was ever pooled, so
  chunks #1–#7 of the document the query asks for are scored as irrelevant.
- **Labels encode an intent the query does not state.** For "How to make a
  good first impression?", chunks about first impressions in cold emails and
  pitch decks were scored 0; the annotator meant meeting people in person.
  Any retriever that reads the query literally is penalised. Recording the
  intended reading alongside the query would make such labels reproducible.

### A6. Duplicate notes split the credit

**What happens.** The export contains a "Document Hub" folder and a
"Document Hub (1)" folder (136 notes under the latter). *As reported:* 72
pairs share a title and 7 pairs are byte-identical. Identical chunks compete
for top-10 slots, and on the generated set only one of the pair counts as the
source note. Counting a same-title or identical-text twin as a hit moves the
winner's file_recall@10 over all 294 queries from 0.721 to 0.748 (Qwen alone
0.588 → 0.616, BGE-M3 alone 0.565 → 0.578, lexical alone 0.619 → 0.639).

**Possible next step.** Deduplicate at ingest (skip a chunk whose normalised
text hash already exists) or exclude the `(1)` folder from the corpus.

### A7. Latency is not measured

No run records how long a query takes. Each query runs two local embedding
models plus three database queries; the lexical arm's slowest query was
2,100 ms before the common-word cut and 24 ms after, which is the only timing
on record. Any future change (a reranker, a larger model) needs a baseline to
compare against.

---

## Part B — Retrieval behaviour

### B1. Dates are not understood

**What happens.** Nothing in the pipeline parses dates. A month name works
only when it appears literally in the text; a year is actively discarded; a
relative date ("last week", "this quarter") is meaningless.

**Evidence.** "what did I write in october 2025" → the lexical arm keeps
`october` and `write` and **drops `2025`**, because `2025` appears in 22% of
chunks and the common-word cut is 15% (`2026` is 17% and is also dropped).
The top 5 were all Daily Check In notes from October 2025 — but only because
every October note in the corpus is from 2025; October notes from another
year would tie exactly. The dense arms see the date as text and are unreliable
on specific numbers.

**Possible next step.** Parse a `date` from dated titles (`@October 14, 2025
10:00 AM` is a common Notion pattern in this corpus) into chunk metadata and
support a date filter or boost. Relative dates additionally need a query
rewriting step with today's date, which does not exist yet.

### B2. Metadata is title only, and the dense arms barely see it

**What happens.** The only metadata stored per chunk is the note title. The
dense arms embed chunk body only, so the title reaches them solely through
the first line of chunk 0; later chunks of a long note carry no trace of it.
The folder path (`Life OS/Document Hub/…`) is stored but searched by no arm.
Untitled Notion pages get the 32-character hash as their "title", which the
lexical arm indexes as a word.

**Evidence.** `scripts/ingest.py:47` sets `metadata={"title": ...}` and
nothing else; `title_from` falls back to the raw stem. A sample row in
`chunks_fts` has title `197d52d026fc806f85cfe184362be99c`.

**Note.** Prepending the title to every chunk before embedding was measured
(`baseline-qwen-title`, `rrf-3arm-k10-title`) and made no difference, so this
is not the obvious win it looks like. Folder path and tags remain untested.

### B3. Heading-only chunks reach the top 10

**What happens.** 96 chunks in the corpus are under 50 characters — notes
that consist of a heading and nothing else. They are short enough to embed
close to many queries and to match a rare word with a high per-word score,
and they carry no answer. In the winner run 56 top-10 slots (across 313
queries) went to snippets under 50 characters. On the judged queries alone
the examples are `# Blake Scholl` and `# Bryan Johnson` (for "john knoll"),
`How do I perform?` and `# Builder's Log @May 20, 2026`. A related class is
the chunk that is only a markdown image link: for "How to make a good first
impression?" the lexical arm's rank 1 is a chunk consisting of
`![](https://substackcdn.com/image/...)`.

**Possible next step.** Skip or fold chunks under a minimum length at ingest
(the chunker already folds a short *last* chunk into its predecessor; a note
that is only one short chunk escapes that).

### B4. Several chunks of one note crowd the top 10

**What happens.** Retrieval is per chunk, with no note-level grouping. When a
note is a strong match, several of its chunks fill the list and displace
other notes. For a user this often reads as one result repeated.

**Evidence.** In the winner run, 153 of 313 queries have at least two chunks
from the same note in their top 10; 312 of 3,130 top-10 slots (10%) are a
second or later chunk of a note already present.

**Possible next step.** Measure whether collapsing to one chunk per note (or
capping at two) helps the file-level metrics without hurting ndcg — the
judged labels are per chunk, so the two metrics may disagree.

### B5. Lexical arm limitations

- **No phrase matching.** The query is a bag of stems; "product market fit"
  matches chunks containing the three words anywhere. Four generated queries
  are near-verbatim lines from a unique note and no arm puts the note in its
  top 10: "why does everything feel the same" (the note contains exactly that
  sentence), "no fear of failure", "what was the bias for action point"
  ("Bias for action is the right way to go"), "Ben Next Play" ("Take the
  suggestion from Ben Next Play"). A lexical arm with phrase or proximity
  scoring would answer all four.
- **Hard common-word cut.** `max_df=0.15` is a cliff: a stem at 14.9% counts
  fully, at 15.1% not at all. The example in B1 shows years falling on the
  wrong side. A smooth weighting (BM25-style saturation) would degrade
  gracefully.
- **The cut removes the words that make a multi-word concept.** "How to make
  a good first impression?" loses `make` (48% of chunks), `good` (21%) and
  `first` (19%), leaving only `impress`; every chunk containing "impress*"
  then ties and the tie-break picks a junk chunk (B3). "summarise what's in
  my personal vision doc" loses `person` (20.5%), so the *Personal Vision*
  note — whose title is those two words — covers only `vision` and loses to
  any chunk that happens to contain the rare stems `summaris` and `doc`.
- **Title weight is inert.** The score is the sum of IDF over matched stems
  (roughly 2–5 per stem) plus `ts_rank_cd / (1 + ts_rank_cd)`, which is
  always below 1. The A/B weights on title and body live only in that second
  term, so a title match changes nothing unless two chunks cover exactly the
  same stems. The `setweight` in the schema is doing no ranking work.
- **Digits and words do not match.** "what are the five companies I should
  target" cannot match "a target company list of just 5 companies"; both
  dense arms missed it as well.
- **Ties.** Chunks covering the same stems get near-identical scores and are
  ordered by id; the October query above returned five results tied at 6.25.
- **English stemmer only.** Non-English notes or names inflected in other
  languages are not normalised.
- **Untuned.** `max_df` was set once, not swept.

### B6. Fusion is tuned on twelve queries

**What happens.** `rrf_k=5` was chosen on 12 train queries. The val curve is
flat-to-rising as k falls further (0.825 at k=5, 0.830 at k=2, 0.844 at k=1),
so the exact optimum is uncertain. Arms have equal weight because both
weighted variants scored worse, but only 0.5× and 2× on the lexical arm were
tried. Fusion is rank-only: an arm's confidence (a cosine of 0.9 versus 0.6)
is discarded.

**Possible next step.** Re-check `rrf_k` once A1 and A2 have improved the
labels; do not tune further on the current set.

### B7. No reranking stage

The system is candidate retrieval only: the fused top 10 is returned as-is.
Precision@10 of 0.233 on train means roughly two of ten results are judged
relevant (again, a floor — see A1). A cross-encoder reranker over the fused
top 50 is the standard next stage and has not been tried. It would also need
the latency baseline from A7.

### B8. No query rewriting

The query string goes to all three arms exactly as typed. There is no spelling
correction, no expansion of abbreviations, and no LLM step to turn "that note
where I compared two ways of doing something" into something either arm can
match. The VAGUE query type in the generated set exists to expose this, but
its type label is currently discarded (A4).

### B9. Approximate search once the corpus grows

The dense arms use an HNSW index. At 5,979 rows Postgres chooses a
sequential scan, so today's dense results are exact. The `ef_search` fix sets
the candidate count to the requested depth, which is the minimum needed to
return that many rows, not enough for high recall once the planner switches
to the index (reproduced at 600 rows in the test suite). When the corpus
grows, dense recall becomes approximate and should be re-measured.

### B10. Answers are not measured

The agent (`main.py`) calls `retrieve()` through its `search_notes` tool
(`src/tools/search.py`, added 2026-09-02) and receives the fused top 10 as
JSON, with no relevance cut-off and no citation format. Every number in this
document stops at retrieval: nothing records which chunks the model used,
whether it answered correctly, or whether it named the right note. Until that
is measured, an improvement here can only be assumed to reach the user.

### B11. Fusion improves ordering but buys no recall over BGE-M3 alone

**What happens.** Reciprocal rank fusion rewards agreement between arms. A
chunk that one arm ranks well and the others rank poorly (or not at all
within depth 50) is outvoted by chunks two arms rank moderately. At
`rrf_k=5`, two arms agreeing at ranks 12 and 15 score 1/17 + 1/20 = 0.109,
which beats one arm's rank 6 (1/11 = 0.091). The fused list therefore drops
some chunks a single arm had in its top 10, and the winner's ndcg gain over
the baselines comes from ordering the chunks it keeps, not from finding more.

**Evidence.** Of the 65 relevant chunks across the 17 scored judged queries,
BGE-M3 alone has 54 in its top 10, the fused winner also has 54, Qwen 42, the
lexical arm 20. 11 relevant chunks that one arm had in its top 10 are absent
from the fused top 10 — 9 from BGE-M3 (ranks 4–10), 2 from Qwen (ranks 4–5);
they include three gain-3 chunks for "What do I imagine myself doing when
running 787?" and one for "What are the criteria for my dream jobs?". On the
generated set, 6 of the 23 genuine misses (A3) were in one arm's top 10:
Qwen rank 3 and 10, lexical ranks 3, 6, 6 and 10. The two dense arms disagree
strongly per query, which is why the loss matters: for the 787 query BGE-M3
ranks the positives 1–5 while Qwen ranks them 13, 28 and 45; for "How can I
speak more eloquently?" Qwen finds both positives and BGE-M3 neither.

**Possible next step.** Measure recall@10 alongside ndcg when comparing
fusion variants, so a change that reorders without finding more is visible.
Candidates to test once A1 has improved the labels: a per-arm weight favouring
BGE-M3, or a bonus for a chunk's best single-arm rank so a lone strong vote
is not outvoted by two weak ones.
