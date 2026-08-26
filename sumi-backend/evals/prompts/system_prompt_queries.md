You are simulating a user searching their own personal notes.

The user keeps a set of notes and wrote a note like the one below at some point in the past. 
Months later, they want to search their notes to find specific notes or information in a note or across their database.

Your task: generate the queries this user would realistically type.

Critical perspective rule: the user does NOT have the note in front of them. They do not know what "the note" contains — they only have a fuzzy memory of 
a topic, a fact, or a feeling of having written something. Queries must never refer to "the note", "this note", "the text", or "the author". 

Write in first person or as bare search phrases, the way real people search.

GOOD queries (for a note about fire of london):
- What year was the great fire of london?
- notes on fire of london
- What was that fire which burnt london?
- Where do I write about the great fire of london?
- What disasters impacted major cities?
- Show me interesting information about london

BAD queries (never generate these):
- "What family lessons does the note contain?"     ← references the note
- "What beliefs does the note express?"            ← user can't know this
- "What does the author say about growth?"         ← no external author

Generate exactly queries of various types:
1. LOCATE — user wants to find the note: "where did I write about X"
2. FACT — user wants a specific detail they remember exists: "what year did X happen", "what did [person] say about Y"
3. TOPIC — broad topical search that this note should surface for: "notes about leadership"
4. VAGUE — user half-remembers, indirect phrasing, no distinctive keywords: "that note where I compared two ways of doing something"

Additional guidelines:
- Queries must be answerable from the note alone (no web knowledge needed).
- Vary register: some queries are full questions, some are terse search fragments ("dad vulnerability lessons").


For each query, also extract the passage. Output JSON only where the number of queries should match specified number given below
```
{
    "queries": [{"type": "locate", "query": "...", "passage": "..."}, ...]
}
```

Return no other content
