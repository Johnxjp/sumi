# sumi

A personal RAG system over a Notion export: an agent REPL with tool calling,
plus a retrieval pipeline (chunking → embeddings → pgvector) and an annotation
app for evaluating retrieval quality. See `sumi-backend/AGENTS.md` for
architecture and commands.

## Gmail tools (read-only)

The agent REPL can search and read your Gmail. Tools are provided by a
locally-run [workspace-mcp](https://github.com/taylorwilsdon/google_workspace_mcp)
MCP server (version-pinned, started in `--read-only` mode) and registered into
the agent's tool registry at startup via `sumi-backend/src/mcp_client.py` and
`sumi-backend/src/tools/gmail.py`. Only read tools are allowlisted, and the
Google OAuth consent requests only the `gmail.readonly` scope — the token
cannot send, modify, or delete mail. If the server isn't running, the REPL
starts normally with filesystem tools only.

### One-time Google Cloud setup

1. In a Google Cloud project, enable the Gmail API:
   `gcloud services enable gmail.googleapis.com`
2. Configure the OAuth consent screen: audience **External**, add your own
   Gmail address as a **test user**. Leave the app in **Testing** (publishing
   would require Google verification for the restricted Gmail scope).
3. Create an OAuth client, type **Web application**, with authorized redirect
   URI `http://localhost:8000/oauth2callback`.

### Configure and run

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

### Running the MCP server on a non-local host

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
