#!/usr/bin/env bash
# Runs the local Gmail MCP server (github.com/taylorwilsdon/google_workspace_mcp)
# in read-only mode. Requires GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET
# from a "Web application" OAuth client with authorized redirect URI
# http://localhost:8000/oauth2callback — loaded from .env if present.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
[ -f .env ] && source .env
set +a

exec uvx workspace-mcp==1.25.1 --transport streamable-http --tools gmail --read-only
