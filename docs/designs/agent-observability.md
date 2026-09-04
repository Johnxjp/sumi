# Trace the agent's model and tool calls with Logfire

## Context

Today the only view into what the agent does is `--verbose` console printing: one
line per model turn and per tool call, no timings, no token counts, no view of
what the model was actually sent. The goal is a per-request trace in Pydantic
Logfire showing the agent run, each model call (with the conversation, finish
reason and token usage) and each tool call (arguments, result, duration), so it
is easy to see why the agent did what it did.

Decisions already made:
- **Full content is captured** (user's choice): messages, replies, tool
  arguments and truncated tool results. Logfire's default scrubbing stays on, so
  text near words like "password" or "token" is replaced with a scrubbed marker.
- The token was added to `sumi-backend/.env` as `LOGFIRE_API_KEY`. It is an
  EU-region token; the SDK reads the region from the token, so no base URL is
  needed. **Right now every `app_config` import fails** because `config.py`
  forbids unknown `.env` variables — step 1 fixes that.
- The Logfire MCP server attached to this session is US-region (projects
  chuckle / my-ai / sense), so it cannot query this project. Verification is
  through the Logfire web UI.

## Findings that shape the design

- The model client is the `openrouter` SDK (httpx-based, sync streaming). Logfire
  has no auto-instrumentation for it, so spans are added by hand around
  `client.chat.send` in `src/agent.py:146`.
- One dispatch point for every tool: `run_tool` in `src/tools/core.py:9`.
- `Agent.stream` is a generator; a `with logfire.span()` inside it stays open
  across `yield`. In the REPL that is fine (`Agent.run` drives it on one
  thread). In the web chat, Starlette drives a sync generator with one
  `anyio.to_thread.run_sync` call **per item**, each in a fresh copy of the
  context: the chat/tool spans would lose their parent and OpenTelemetry would
  log "Failed to detach context" on every span exit. Fix: drive the generator on
  a single worker thread (step 5).
- Logfire's attribute names for LLM spans are the OpenTelemetry GenAI
  conventions (`gen_ai.*`), the same ones its OpenAI integration emits; its
  Agents page needs a span with `gen_ai.operation.name="invoke_agent"` and
  `gen_ai.agent.name`.
- Logfire installs a pytest plugin providing the `capfire` fixture (in-memory
  exporter, `send_to_logfire=False`, `console=False`); span tests use it.

## Steps

All commands from `sumi-backend/`.

1. **Dependency + settings.** `uv add "logfire[fastapi]"`. In `src/config.py`
   add `logfire_api_key: str = Field(default="", description=...)` (matches the
   variable already in `.env`; empty means "do not send"). Add
   `LOGFIRE_API_KEY=` to `.env.example` (if file permissions block the edit, tell
   the user the line). Add `[tool.logfire] ignore_no_config = true` to
   `pyproject.toml` so tests that exercise the agent without configuring Logfire
   stay warning-free.

2. **`src/observability.py` (new).**
   - `configure_logfire()`: `logfire.configure(token=key or None,
     send_to_logfire=bool(key), service_name="sumi", console=False)`.
     `console=False` keeps stdout clean for the REPL and the
     "silent when not verbose" test in `tests/test_agent.py`.
   - `genai_messages(history) -> (system_instructions, messages)`: pure function
     converting the OpenAI-style history to the GenAI shape:
     system → `[{"type":"text","content":...}]` (kept separate);
     user/assistant text → `{"role", "parts":[{"type":"text","content"}]}`;
     assistant tool calls → parts `{"type":"tool_call","id","name","arguments"}`
     (arguments parsed from JSON when possible); tool → `{"role":"tool",
     "parts":[{"type":"tool_call_response","id":tool_call_id,"result":content}]}`.
   - `truncate(text, limit)` for tool results (10,000 chars).
   - Call `configure_logfire()` at module level in `src/bootstrap.py` (both
     entry points import it; the web app builds the agent at import time, so
     this is the one shared startup hook).

3. **Spans in `src/agent.py` (`Agent.stream`).**
   - Whole run: `logfire.span("invoke_agent sumi", **{"gen_ai.operation.name":
     "invoke_agent", "gen_ai.agent.name": "sumi"})` around the `try` body.
   - Each model call: `logfire.span("chat {model}", ...)` around `send` plus the
     chunk loop, with `gen_ai.operation.name="chat"`,
     `gen_ai.provider.name="openrouter"`, `gen_ai.request.model`,
     `gen_ai.system_instructions`, `gen_ai.input.messages` (from
     `genai_messages`). On exit set `gen_ai.output.messages` (the built
     assistant message), `gen_ai.response.finish_reasons=[finish_reason]`,
     `reasoning`, and `gen_ai.usage.input_tokens` / `output_tokens` when the
     final chunk carries `usage` (use `getattr(chunk, "usage", None)`: the
     test's `USAGE_CHUNK` has no such attribute). Read usage in
     `StreamedTurn.add` where empty-choice chunks are already handled.
   - Leave the existing `--verbose` printing as it is.

4. **Tool span in `src/tools/core.py` (`run_tool`).**
   `logfire.span("execute_tool {name}", ...)` with
   `gen_ai.operation.name="execute_tool"`, `gen_ai.tool.name`,
   `gen_ai.tool.call.arguments` (raw string); on exit set
   `gen_ai.tool.call.result` (stringified, truncated) and `success`. Errors are
   already turned into `(False, message)` here, so the failure branch sets
   `success=False` and the message as the result.

5. **Web chat: one thread per reply + request spans.**
   - `src/chat/stream.py`: keep the current frame logic as a sync helper; make
     `stream_reply` an async generator that runs the helper on **one** worker
     thread (`anyio.to_thread.run_sync`) and pushes frames through an
     `anyio` memory object stream (`anyio.from_thread.run(send.send, frame)`),
     yielding from the receive side. The agent's spans then stay nested because
     the generator is resumed in one context.
   - `src/chat/app.py`: `logfire.instrument_fastapi(app)` after the app is
     created, so `POST /api/chat` is the root span and the worker thread inherits
     it. The endpoint can stay a sync `def`; `StreamingResponse` accepts the
     async iterator.

6. **Tests.**
   - `tests/test_observability.py`: `genai_messages` for a history containing
     system, user, assistant-with-tool-calls and tool messages; `truncate`.
   - `tests/test_agent.py`: with `capfire`, a tool-call turn then a text turn
     produces one `invoke_agent` span (`gen_ai.agent.name == "sumi"`) with two
     child `chat model` spans carrying finish reasons and input/output messages,
     and token counts when a usage chunk has `usage`. Existing tests unchanged.
   - `tests/test_tool_core.py`: `run_tool` emits `execute_tool <name>` with
     arguments and result; a failing tool gives `success=False`.
   - `tests/test_chat_stream.py`: adapt the two `stream_reply` tests to the async
     generator (collect with `asyncio.run`). Add one test with `capfire` and a
     fake agent whose `stream` opens a span across `yield`s: the frames arrive
     and the span's child (opened after a yield) has it as parent — the
     regression guard for step 5.

7. **Docs.** `docs/architecture.md`: in the Agent paragraph, one or two
   sentences on the trace shape (`invoke_agent` → `chat` → `execute_tool`, web
   requests as the root span, one worker thread per reply) and in
   Configuration add `LOGFIRE_API_KEY` (optional; empty = nothing sent). Check
   `docs/designs/chat-ui.md` for any sentence about `stream_reply` being a sync
   generator and fix it. Record the design and the threading reason in
   `docs/plans/completed/logfire-tracing.md`.

Not in scope (say so in the recap): httpx-level HTTP spans, system metrics,
spans inside the retrieval arms, a content on/off switch.

## Verification

1. `uv run pytest` and `uv run ruff check . --fix && uv run ruff format .` pass.
2. Confirm settings import again: `uv run python -c "from src.config import app_config"`.
3. REPL: `uv run main.py`, ask a question that needs `search_notes`. In the
   Logfire project's Live view: one trace `invoke_agent sumi` → `chat <model>` →
   `execute_tool search_notes` → `chat <model>`; the transcript renders from the
   `gen_ai` messages; token counts present. The Agents page lists "sumi".
4. Web: `uv run uvicorn src.chat.app:app --port 8766` + `pnpm dev`, send a
   message. Trace root is `POST /api/chat` with the agent spans nested; the
   server console shows no "Failed to detach context"; streaming in the browser
   still arrives incrementally.
5. With `LOGFIRE_API_KEY` empty, the REPL and tests run with no network calls to
   Logfire.
