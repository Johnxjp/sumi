"""Manual end-to-end check against the locally-running workspace-mcp server.

Start the server first (scripts/run_gmail_mcp.sh), then run from the repo root:

    uv run python -m scripts.gmail_smoke

The first tool call opens a browser window for Google consent.
"""

from src.config import app_config
from src.mcp_client import McpClient
from src.tools.gmail import GMAIL_READ_TOOLS


def main() -> None:
    client = McpClient(app_config.gmail_mcp_url)

    print(f"Discovered tools at {app_config.gmail_mcp_url}:")
    for tool in client.list_tools():
        tag = "allowed" if tool.name in GMAIL_READ_TOOLS else "filtered"
        params = ", ".join((tool.input_schema or {}).get("properties", {}))
        print(f"  [{tag}] {tool.name}({params})")

    print("\nsearch_gmail_messages (newer_than:7d):")
    print(client.call_tool("search_gmail_messages", {"query": "newer_than:7d"}))


if __name__ == "__main__":
    main()
