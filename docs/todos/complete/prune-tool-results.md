# Replace used `search_notes` results in the agent's history with stubs

Status: done 2026-09-03 (commit 0a7e889). Raised 2026-09-02 after wiring
`search_notes` into the agent. Kept as the design record; current behaviour is
described in `docs/architecture.md`.

## Problem

`Agent.run` (`sumi-backend/src/agent.py`) appends every tool result to
`conversation_history` as a `role: "tool"` message and never removes it. The
history is re-sent on every API call, so each result is paid for on every
later turn, for the rest of the session.

`search_notes` is the tool that makes this expensive. Measured on the query
"personal vision", one result (10 chunks of up to 2,000 characters) is about
18,000 characters, roughly 4,500 tokens. A session with a dozen searches is
past a third of a 128k window, and once the window is full the API returns an
error (see `context-compaction.md`). The raw chunks are only useful until the
model has answered; after that they are dead weight.

Other tools are out of scope here. `read_file` returns a whole note, which is
also large, but the model asked for that note on purpose; grep, directory
listing and the Gmail tools return little.

## Proposed fix

When `run()` produces its final answer, find the tool messages from that turn
whose tool call was `search_notes` and replace their content with a one-line
stub. Keep the message and its `tool_call_id` so the assistant-message /
tool-message pairing the API requires stays valid. Leave every other tool's
result untouched.

The stub keeps the query and, for every chunk, its rank, title and `source`
path. Titles are small even for all ten, and the `source` path is what
`read_file` needs if the model wants a note back:

```
[search_notes("personal vision") returned 10 chunks:
 1 Personal Vision (Life OS/Personal Vision 146d….md)
 2 What is important to me (Journal/What is important to me 1a8d….md)
 ...]
```

The model's answer stays in history. A follow-up that needs the chunks again
costs one more search or one `read_file`, which is cheaper than carrying every
result forever.

## Done when

- A test shows that after `run()` returns, that turn's `search_notes` tool
  messages hold stubs listing every returned title and source, other tools'
  results are unchanged, and every `tool_call_id` is unchanged.
- A REPL session's history size stays roughly flat across repeated searches
  (check by printing `len(str(agent.conversation_history))` per turn).
- `docs/architecture.md` part 1 describes the behaviour and this note is
  deleted.
