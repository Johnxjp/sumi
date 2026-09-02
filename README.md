# sumi

A personal RAG system over a Notion export: an agent REPL with tool calling,
plus a retrieval pipeline (chunking → embeddings → pgvector) and an annotation
app for evaluating retrieval quality.

`AGENTS.md` is the map of the repository. Design docs live in `docs/`:
architecture, retrieval (overview and known weaknesses), the annotation tool,
Gmail/MCP, testing and coding standards.

## Gmail tools (read-only)

The agent REPL can search and read your Gmail through a locally run
[workspace-mcp](https://github.com/taylorwilsdon/google_workspace_mcp) server
(version-pinned, `--read-only`, `gmail.readonly` scope only — the token cannot
send, modify or delete mail). If the server isn't running, the REPL starts
without Gmail tools. Setup, running, and the checklist for hosting the
server elsewhere: `docs/mcp-integration.md`.
