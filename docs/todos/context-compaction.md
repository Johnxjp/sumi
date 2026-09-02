# Compact the agent's conversation history before the context window fills

Status: open. Raised 2026-09-02. `search_notes` results are already replaced
by stubs once a turn ends (see `docs/architecture.md`), which removes the
largest source of growth and makes compaction rare.

## Problem

`Agent.run` (`sumi-backend/src/agent.py`) has one compaction path, the
`finish_reason == "length"` branch, and it does not address a full context:

- `length` means the model's *output* hit its token limit. A full *input*
  context is not a finish reason; the API returns an error, which the REPL
  does not catch, so the session crashes. (The docstring's TODO about
  dangling tool calls is this problem.)
- When the branch does fire it keeps the last five messages by count. That
  can cut between an assistant message that made tool calls and the tool
  messages answering it, leaving an orphaned tool result the API rejects.

There is no token counting anywhere in the loop.

## Proposed fix: a sliding window over the history

Before each API call:

1. Read the token count of the history. The previous response's
   `usage.prompt_tokens` (OpenRouter returns it) is enough; no tokenizer
   library needed. Compare against the model's window minus headroom for the
   answer.
2. If over budget, drop the oldest exchanges until under it, always keeping
   the system prompt. Drop in valid units: a user message with the assistant
   reply, or an assistant tool-call message together with all of its tool
   messages. Never split a pair.
3. Optionally, before dropping, ask the model to summarise the dropped
   messages into one short message kept at the top, so earlier context is not
   lost entirely. One extra model call per compaction.

Also catch the context-length API error in `run()` and compact then retry,
so a session degrades instead of crashing.

The window size per model is not known to the code today; it needs a config
field or a lookup by model name.

## Done when

- Tests show: a history over budget is trimmed to under it; a tool-call
  message and its tool results are dropped together or not at all; the system
  prompt survives.
- A long REPL session (twenty or more searches) does not crash.
- `docs/architecture.md` part 1 describes the behaviour and this note is
  deleted.
