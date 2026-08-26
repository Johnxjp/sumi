import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.client.client import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp.types import TextContent, Tool


class McpClient:
    """Sync facade over the async MCP SDK: opens a fresh session per call,
    which keeps the callers synchronous at the cost of a handshake per call —
    fine at REPL volume."""

    def __init__(self, url: str, get_token: Callable[[], str] | None = None):
        self.url = url
        self.get_token = get_token

    async def _run_session(self, operation: Callable[[Client], Awaitable[Any]]) -> Any:
        headers = (
            {"Authorization": f"Bearer {self.get_token()}"} if self.get_token else None
        )
        http_client = create_mcp_http_client(headers=headers)
        transport = streamable_http_client(self.url, http_client=http_client)
        async with Client(transport) as client:
            return await operation(client)

    def list_tools(self) -> list[Tool]:
        result = asyncio.run(self._run_session(lambda client: client.list_tools()))
        return result.tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = asyncio.run(
            self._run_session(lambda client: client.call_tool(name, arguments))
        )
        text = "\n".join(
            block.text for block in result.content if isinstance(block, TextContent)
        )
        if result.is_error:
            raise RuntimeError(text or f"MCP tool '{name}' returned an error")
        return text
