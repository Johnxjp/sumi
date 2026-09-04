# Web chat

A single-page web app for talking to the agent from a browser instead of the
terminal. Code: `sumi-frontend/` (Next.js, TypeScript, pnpm) and
`sumi-backend/src/chat/` (FastAPI). Run each from its own folder:

```
cd sumi-backend  && uv run uvicorn src.chat.app:app --port 8766
cd sumi-frontend && pnpm install && pnpm dev        # → http://localhost:3000
```

The page talks to the backend at `http://localhost:8766`. To point it
elsewhere, set `NEXT_PUBLIC_API_URL` in `sumi-frontend/.env.local`.

## What it does

One conversation, one user. You type a question in the box at the bottom;
the reply appears word by word as the model writes it, and each tool call the
agent makes shows as a one-line status ("Searching notes for “deep work”")
above the text, in the order it happened. "New chat" clears the conversation
on both sides. Nothing is persisted: restarting the backend forgets the
conversation, and reloading the page forgets what was on screen.

The reply is shown as plain text. Markdown the model writes is not rendered,
and there are no citations or links to notes yet.

## How the reply reaches the page

The agent (`src/agent.py`) is a generator: `Agent.stream()` yields typed
events while it works. `Agent.run()`, which the terminal REPL calls, is a thin
wrapper that joins the text of the final turn. Two event types exist:

- `TextDelta(text)`: a piece of assistant text, as the model streams it.
  Every model call streams, so text the model writes before a tool call
  ("Let me look…") is emitted too, in order.
- `ToolCall(name, arguments)`: the model asked for a tool; emitted just before
  the tool runs, with the arguments as the JSON string the model produced.

`POST /api/chat` (`src/chat/app.py`, body `{"message": "…"}`) runs
`Agent.stream()` and forwards each event as a server-sent event (SSE): one
`data:` line holding a JSON object, ended by a blank line (`src/chat/stream.py`).
The payloads are `{"type": "text", "text": …}` and
`{"type": "tool_call", "name": …, "arguments": {…}}` (the arguments parsed,
`{}` if they were not a JSON object), then `{"type": "done"}`, or
`{"type": "error", "message": …}` if anything failed. `POST /api/reset` clears
the history. The endpoint is synchronous, but it returns an async generator
that runs the whole reply on one worker thread, so the event loop is not blocked
while the agent works. The single thread also keeps the agent's trace spans
nested: Starlette drives a plain sync generator with one thread call per item,
each in a fresh copy of the context, which breaks any span held open across a
yield (`docs/designs/agent-observability.md`). At startup the server
loads both embedding models (`HybridRetriever.load_models()`), so the first
question is not slower than the rest.

If the model or a tool fails mid-turn, the agent deletes the whole exchange
from its history (back to where the turn started) so the next message starts
from a consistent state. The page shows the error under the reply.

The server's console is its log. The agent runs in verbose mode there, so
every model turn prints one line (finish reason, how many characters of text
and how many tool calls it produced, and the model's reasoning) and every tool
call prints its name and arguments. A failed reply is logged with its
traceback before the `error` event is sent. An empty reply therefore shows up
as a turn with `text=0 chars, tool_calls=0`, followed by whatever the model
was reasoning about.

In the browser, `lib/api.ts` reads the response body as a stream, `lib/sse.ts`
splits it into frames, and `lib/conversation.ts` folds each event into the
assistant message. A message is an ordered list of blocks: text is appended to
the last text block, a tool call adds a tool block, and the blocks render top
to bottom (`components/Transcript.tsx`). `describeToolCall` turns a tool name
and its arguments into the status line, with a generic "Using …" line for
tools it does not know, such as the Gmail ones.

### Showing intermediate steps later

To stream the model's reasoning as well, add a `Reasoning(text)` event in
`src/agent.py` (`StreamedTurn` already collects `delta.reasoning`), a
`{"type": "reasoning"}` payload in `src/chat/stream.py`, a `reasoning` block
in `lib/types.ts` and `lib/conversation.ts`, and a way to render it in
`components/Transcript.tsx`. Transport and page structure stay as they are.

## Design

The look follows the name: sumi is Japanese ink. The palette is one ink at
several dilutions on near-white paper, with no colour except a vermilion send
button, like the red seal on an ink painting. Questions and replies are set in
Newsreader (a serif made for reading on screen); the small status and error
lines in IBM Plex Sans. Both fonts are self-hosted by `next/font`, so the page
makes no request to Google. There are no chat bubbles: a question reads as a
heading, the reply as body text below it, and a hairline separates exchanges,
like a page of notes. All styling lives in `app/globals.css`.

## Tests

- `sumi-backend/tests/test_agent.py`: the event stream, text and tool calls in
  order, tool-call arguments reassembled from split chunks, the exchange
  dropped on failure, compaction when a reply is cut off.
- `sumi-backend/tests/test_chat_stream.py`: SSE encoding, the `done` and
  `error` frames, argument parsing.
- `sumi-frontend/lib/*.test.ts` (Vitest, `pnpm test`): the SSE parser, the
  message reducer and the tool status lines.

The React components have no unit tests; check the page by hand.
