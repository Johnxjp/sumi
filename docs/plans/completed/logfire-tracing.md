# Trace the agent's model and tool calls with Logfire

Status: done 2026-09-04. Raised because the only view into an agent run was
`--verbose` console printing. Kept as the design record; current behaviour is
described in `docs/architecture.md`, and the fuller design in
`docs/designs/agent-observability.md`.

## Problem

One line per model turn and per tool call on the console, and nothing else. No
timings, no token counts, and no record of what the model was actually sent, so
a bad answer could not be examined after the fact.

## What shipped

Pydantic Logfire — an observability service built on OpenTelemetry — receives a
trace per agent run:

- `invoke_agent sumi` for the whole run. Logfire's Agents page keys off
  `gen_ai.operation.name="invoke_agent"` plus `gen_ai.agent.name`.
- `chat {gen_ai.request.model}` per model call, carrying the conversation
  (`gen_ai.input.messages`, `gen_ai.system_instructions`,
  `gen_ai.output.messages`), the stop reason, the model's reasoning, and token
  counts.
- `execute_tool {gen_ai.tool.name}` per tool call, with the arguments, the
  result (truncated at 10,000 characters) and whether it succeeded.
- In the web chat, the HTTP request is the root span
  (`logfire.instrument_fastapi`).

Attribute names and message shapes follow the OpenTelemetry GenAI semantic
conventions, which is what makes Logfire render a model call as a readable
transcript rather than a bag of attributes. `src/observability.py` holds the
setup and the history-to-GenAI conversion.

Content is captured in full — messages, replies, tool arguments and truncated
tool results — which was a deliberate choice. Logfire's default scrubbing stays
on, so text near words like "password" or "token" is replaced with a marker.

`LOGFIRE_API_KEY` in `.env` is the credential. It is optional: empty means
nothing is sent, and the token is passed explicitly to `logfire.configure()`, so
the SDK never reads the environment itself. The token names its own region, so
no base URL is configured.

## Why the web chat runs one worker thread per reply

`Agent.stream` is a generator, so a span opened inside it stays open across
`yield`.

Starlette hands a sync generator to `iterate_in_threadpool`, which calls
`anyio.to_thread.run_sync(next, iterator)` **once per item**. Each of those
calls does its own `copy_context()`, so a context variable set while producing
item N is gone by item N+1. OpenTelemetry keeps the current span in a context
variable, so the consequence is not a mis-parented child: the spans beneath the
open span lose the whole attached context and start **new traces of their own**,
and the failed `detach` shows up as "Failed to detach context" in the log.

The fix is not thread identity — it is that one `run_sync` call is one copied
context. `stream_reply` is therefore an async generator that runs the entire
reply inside a single `run_sync` call, pushing frames to the event loop through
an `anyio` memory object stream. Do not "optimise" this back to per-item
threading.

Two details that matter if this code is touched again:

- The producer swallows `BrokenResourceError`/`ClosedResourceError`. Without
  that, a browser disconnecting mid-reply turns a clean cancellation into an
  `ExceptionGroup` that escapes to the ASGI server on every disconnect.
- A memory object stream buffer of 0 is deliberate: it gives backpressure, so
  the agent thread blocks until each frame is on the socket.

`tests/test_chat_stream.py::test_streaming_response_keeps_the_agents_spans_in_one_trace`
guards this through a real `TestClient` request; it fails if `stream_reply` goes
back to being a sync generator.

## Not covered

httpx-level HTTP spans, system metrics, spans inside the retrieval arms, and a
switch to turn content capture off. Nothing measures the quality of the answers
the agent produces — only what it did.
