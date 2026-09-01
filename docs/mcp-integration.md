# Gmail via MCP: How It Was Added and Why

How sumi's agent got read-only Gmail tools — what we were trying to achieve,
the options considered (including one we fully built and then abandoned), where
we landed, and how the pieces work. Everything referenced here lives in
`sumi-backend/` unless noted. Written August 2026; a newcomer should be able to
read this alone and understand both the design and its history.

## Background

Sumi's agent CLI (`main.py` → `src/agent.py`) is a terminal REPL running an
OpenRouter tool-calling loop. Its original tools were filesystem reads over the
notes directory (`src/tools/file.py`), registered in a simple registry
(`src/tools/registry.py`) that holds OpenAI-style function schemas and
dispatches calls synchronously.

The goal: let the agent **act on the owner's personal Gmail** — search the
inbox, read messages and threads, list labels — strictly **read-only**. Two
future ambitions shaped the design without being built:

1. **More providers later.** Outlook is explicitly next. The mail-specific
   parts must be thin; the mechanism must be reusable.
2. **Email as a trigger.** Eventually, new mail should be able to kick off
   workflows (most likely a cron poller). The Gmail client therefore must be
   importable outside the REPL.

## Why MCP at all

MCP (Model Context Protocol) is an open protocol where a *server* exposes tools
(name + JSON schema + execution) and a *client* discovers and calls them over a
transport (stdio for local subprocesses, "streamable HTTP" for network
servers). Building against MCP instead of a provider SDK means sumi's side is
generic: any mail provider that has an MCP server plugs into the same
discovery/registration/dispatch code, which serves ambition #1 directly. The
alternative — hand-writing Gmail API tools with `google-api-python-client` —
was seriously considered (see below) and would have worked, but every future
provider would then be another bespoke module.

## The path to the current design

### Attempt 1: Google's official Gmail MCP server (built, then abandoned)

Google runs a managed Gmail MCP server at
`https://gmailmcp.googleapis.com/mcp/v1` (streamable HTTP, OAuth 2.0 bearer
tokens from your own GCP project). This was the original choice — official,
hosted, nothing to run locally — and the integration was **fully implemented
and tested** against its documented contract: an OAuth module minting tokens
with `google-auth` (desktop-app flow, cached token in `secrets/`), and the
bearer header injected into every MCP call.

It died on an external gate: the server is a **Developer Preview** feature,
available only to members of the Google Workspace Developer Preview Program —
and that program **rejects personal @gmail.com accounts**; enrollment requires
an email on a Workspace domain. The options were:

- **Buy a Workspace identity** (domain + subscription, ~$100+/yr, or an
  unverified ~$10/yr hack via Cloud Identity Free). Rejected: recurring cost to
  depend on a preview API that can change without notice.
- **Wait for GA.** Rejected: we wanted it working now.
- **Direct Gmail API tools, no MCP.** The plain Gmail API has no preview gate.
  This was briefly the recommendation — zero new trust, works today — at the
  cost of abandoning MCP for Gmail. Superseded by the community server below.
- **Anthropic's hosted Gmail connector** was ruled out earlier: it is tied to
  Claude products, and sumi's agent runs on OpenRouter.

The dead code (google-auth plumbing, token cache, auth script) was deleted, not
commented out; it exists in git history if the official server ever GAs.

### Attempt 2: a community server, run locally (where we landed)

[`taylorwilsdon/google_workspace_mcp`](https://github.com/taylorwilsdon/google_workspace_mcp)
is a Python MCP server for the whole Workspace suite (Gmail, Drive, Calendar,
…) that talks to the plain Google APIs — so no preview program — while keeping
the MCP shape sumi was built for. Before adopting it we evaluated it:

- **Health:** ~3.1k stars, MIT, very active (multiple releases per week, pushed
  the day we checked), zero published security advisories. Known weakness:
  single dominant maintainer (~90% of commits), no formal audit.
- **Scope discipline (verified in its source, not its README):** every tool
  declares the OAuth scopes it needs; read tools require only
  `gmail.readonly`. Its `--read-only` flag does two independent things:
  removes every tool whose scopes aren't read-only, **and** generates the
  Google consent request from a readonly-only scope map
  (`auth/scopes.py`) — so the token itself never gains write powers.
- **Empirical confirmation:** we ran the pinned server with dummy credentials
  and parsed the consent URL it produced. It requested exactly
  `gmail.readonly` plus basic identity scopes (`openid`, `userinfo.email`,
  `userinfo.profile`). No send, no compose, no modify.

The residual trust cost — running third-party code with mail access — is
mitigated by the version pin (`workspace-mcp==1.25.1` in
`scripts/run_gmail_mcp.sh`) and by the fact that even a fully compromised
server could only *read* mail, never send or delete.

## Where we landed: the architecture

Three layers, from generic to specific:

**1. `src/mcp_client.py` — a generic MCP client.** `McpClient(url,
get_token=None)` is a synchronous facade over the official `mcp` Python SDK
(v2). Each call opens a fresh streamable-HTTP session via `asyncio.run`,
performs the operation, and closes. Decisions inside it:

- **Sync facade, per-call sessions.** The agent loop and `run_tool` dispatch
  are synchronous; the MCP SDK is async. We chose per-call `asyncio.run` over
  (a) a persistent background event-loop thread and (b) converting the agent
  loop to async, because at REPL volume the extra handshake round-trips are
  invisible next to LLM latency, and it required zero changes to
  `src/agent.py`, `src/tools/registry.py`, or `src/tools/core.py`. If call
  volume ever grows (e.g. the trigger poller), a background-loop thread can
  replace the internals without changing the interface.
- **Optional bearer token.** The local server needs no auth header;
  `get_token` exists because a *remote* deployment (or the official Google
  server, if revived) does. Errors in tool results (`is_error`) become
  `RuntimeError`s, which the existing `run_tool` already converts into
  `"Error: ..."` tool messages for the model.

**2. `src/tools/mcp.py` — generic discovery and registration.**
`register_mcp_tools(reg, client, prefix, allowlist)` fetches `tools/list` from
the server, keeps only allowlisted names, converts each MCP `inputSchema`
mechanically into the registry's schema format, and registers a closure that
routes the call back through the client. Decisions:

- **Dynamic discovery over hardcoded schemas.** Tool schemas come from the
  server at startup, so they can't drift from what the server actually
  accepts. (This paid off immediately: the live server's schemas differed from
  what static code-reading predicted — see `user_google_email` below.)
- **Explicit registration, not import side-effects.** The filesystem tools
  register themselves on import (`src/tools/file.py`); the MCP tools do not,
  because registration performs network IO. `main.py` calls
  `register_gmail_tools()` explicitly.
- **Graceful degradation.** Any discovery failure — server not running,
  network error — prints one warning and registers nothing; the REPL runs with
  filesystem tools only.

**3. `src/tools/gmail.py` — the Gmail provider, which is almost nothing.** A
six-name allowlist and a two-line function building the client from config.
This thinness is deliberate and was a mid-design correction: the first plan
draft had Gmail-specific modules everywhere, and was reshaped when the
multi-provider ambition surfaced. **Adding Outlook means: an allowlist, config
fields, and one `register_mcp_tools` call.** No new framework — a provider
registry was explicitly rejected as premature for two providers.

The allowlist: `search_gmail_messages`, `get_gmail_message_content`,
`get_gmail_messages_content_batch`, `get_gmail_thread_content`,
`get_gmail_threads_content_batch`, `list_gmail_labels`. Two read-only tools
were deliberately excluded: `get_gmail_attachment_content` (returns base64
blocks that would flood the agent's conversation history) and
`list_gmail_filters` (drags in the Gmail settings scope).

## Read-only, three times over

Defense in depth — each layer alone would suffice:

1. **Client allowlist** (`GMAIL_READ_TOOLS`): write tools are never registered,
   so the model cannot call them.
2. **Server `--read-only`**: write tools are not even exposed by the server.
3. **OAuth scope**: the token holds only `gmail.readonly`; a write attempt
   would be rejected by Google itself.

## Operational shape

The server runs as a separate local process: `./scripts/run_gmail_mcp.sh`
sources `.env`, then launches the pinned `workspace-mcp` on
`http://localhost:8000/mcp` with `--tools gmail --read-only`. The server owns
Google OAuth end-to-end: on the first tool call it returns/opens an
authorization URL, and caches tokens in `.credentials/` (gitignored).

Configuration lives in `src/config.py` (`gmail_mcp_url`,
`google_oauth_client_id`, `google_oauth_client_secret`, `user_google_email`).
Two non-obvious details:

- `Settings` uses `extra="forbid"`, so **any env var in `.env` must have a
  matching field** — this is why sumi declares fields for variables only the
  server process consumes.
- `USER_GOOGLE_EMAIL` matters more than it looks: when set, the server rewrites
  its tool schemas to drop the otherwise-*required* `user_google_email`
  argument from every tool, so the model never needs to know the address.

The Google Cloud side needs a project with the Gmail API enabled, an External
consent screen with the owner as **test user**, and a **Web application**
OAuth client with redirect URI `http://localhost:8000/oauth2callback`. The app
stays in Testing (publishing a restricted-scope app requires Google
verification), which means Google expires refresh tokens after ~7 days —
re-consent is a recurring fact of life, and the server surfaces a fresh auth
URL when it happens. Setup steps and the checklist for moving the server to a
non-local host follow.

## Setup and running

One-time Google Cloud setup:

1. In a Google Cloud project, enable the Gmail API:
   `gcloud services enable gmail.googleapis.com`
2. Configure the OAuth consent screen: audience **External**, add your own
   Gmail address as a **test user**. Leave the app in **Testing** (publishing
   would require Google verification for the restricted Gmail scope).
3. Create an OAuth client, type **Web application**, with authorized redirect
   URI `http://localhost:8000/oauth2callback`.

Add to `sumi-backend/.env`:

```
GOOGLE_OAUTH_CLIENT_ID=<client_id>
GOOGLE_OAUTH_CLIENT_SECRET=<client_secret>
USER_GOOGLE_EMAIL=<your_gmail_address>
```

Then, from `sumi-backend/`:

1. `./scripts/run_gmail_mcp.sh` — starts the MCP server on port 8000.
2. `uv run python -m scripts.gmail_smoke` — verifies discovery and runs a
   search. The first call opens a browser window for Google consent; tokens
   are cached in `sumi-backend/.credentials/` (gitignored).
3. `uv run main.py` — the REPL now has the Gmail tools.

Because the OAuth app stays in Testing mode, Google expires refresh tokens
after about 7 days — when calls start failing, the server responds with a
fresh authorization URL; open it to re-consent.

## Running the server on a non-local host

The local setup deliberately skips authentication on the MCP endpoint itself,
which is only safe on localhost. Moving the server to a remote host changes
five things:

1. **Authenticate the MCP endpoint.** A remote endpoint fronting your mailbox
   must not be reachable unauthenticated. Run workspace-mcp with
   `MCP_ENABLE_OAUTH21=true` so the endpoint requires bearer tokens, and pass
   a token from sumi — `McpClient(url, get_token=...)` already supports this;
   only `register_gmail_tools` in `sumi-backend/src/tools/gmail.py` needs to
   supply the callable.
2. **Serve over HTTPS** behind a reverse proxy; plain HTTP is only acceptable
   on localhost (`OAUTHLIB_INSECURE_TRANSPORT` must not be set in production).
3. **Update the OAuth redirect URI.** Add `https://<host>/oauth2callback` to
   the client's authorized redirect URIs in Google Cloud console and set
   `GOOGLE_OAUTH_REDIRECT_URI` to the same value on the server.
4. **Point sumi at the new endpoint**: `GMAIL_MCP_URL=https://<host>/mcp` in
   `sumi-backend/.env`.
5. **Protect the token store.** `.credentials/` then lives on the remote host;
   restrict access to it, or use workspace-mcp's Redis/GCS token-storage
   backends (it also has a stateless mode for locked-down containers).

Keep `--read-only` and the version pin in `scripts/run_gmail_mcp.sh` regardless
of where the server runs.

## Verification approach

Unit tests (`tests/test_mcp_client.py`, `tests/test_mcp_tools.py`,
`tests/test_gmail_tools.py`) cover the schema conversion, allowlist filtering,
dispatch routing, header handling, error flattening, and degradation paths
with mocked sessions. The end-to-end path can't run in CI (it needs OAuth and
a live server), so it is scripted instead: `scripts/gmail_smoke.py` prints the
server's full tool list tagged `[allowed]`/`[filtered]` and runs a real
search. During development the pipeline was additionally verified against the
actually-running pinned server: discovery, registration, schema shape, the
pre-auth error path, and the consent-URL scope audit above.

## Known limitations and future work

- **No label listing beyond names, no drafts, no attachments** in the current
  allowlist; each is one line away if needed (attachments would want a size
  guard first).
- **Weekly re-consent** while the OAuth app is in Testing mode.
- **Official Google server**: if it leaves Developer Preview, switching back is
  `gmail_mcp_url` + a `get_token` callable + a new allowlist (its tool names
  differ). The git history contains the complete earlier implementation.
- **Triggers**: the planned shape is a cron/launchd script importing
  `McpClient`, polling `search_gmail_messages` with a `newer_than:`/last-seen
  watermark, and invoking `Agent.run`. Nothing in the current design blocks
  it; nothing for it has been built.
