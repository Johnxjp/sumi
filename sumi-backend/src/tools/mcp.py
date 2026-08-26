from collections.abc import Callable
from typing import Any

from mcp.types import Tool

from src.mcp_client import McpClient
from src.tools.registry import ToolRegistry


def convert_mcp_tool_schema(tool: Tool, prefix: str) -> dict[str, Any]:
    return {
        "name": f"{prefix}{tool.name}",
        "description": tool.description or "",
        "parameters": tool.input_schema,
    }


def build_tool_fn(client: McpClient, name: str) -> Callable[..., str]:
    def call_mcp_tool(**kwargs: Any) -> str:
        return client.call_tool(name, kwargs)

    return call_mcp_tool


def register_mcp_tools(
    reg: ToolRegistry, client: McpClient, prefix: str, allowlist: set[str]
) -> int:
    try:
        tools = client.list_tools()
    except Exception as e:  # noqa: BLE001 — any discovery failure must disable the toolset, not crash the REPL
        print(f"[warn] MCP tool discovery failed for {client.url}: {e}")
        return 0

    count = 0
    for tool in tools:
        if tool.name not in allowlist:
            continue
        schema = convert_mcp_tool_schema(tool, prefix)
        reg.register_tool(schema["name"], build_tool_fn(client, tool.name), schema)
        count += 1
    return count
