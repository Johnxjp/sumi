from typing import Any
from unittest import mock

import pytest
from mcp.types import Tool

from src.mcp_client import McpClient
from src.tools.mcp import convert_mcp_tool_schema, register_mcp_tools
from src.tools.registry import ToolRegistry


def build_tool(
    name: str, description: str = "desc", schema: dict[str, Any] | None = None
) -> Tool:
    return Tool(
        name=name, description=description, inputSchema=schema or {"type": "object"}
    )


@pytest.mark.parametrize(
    ("prefix", "name", "expected_name"),
    [
        ("gmail_", "search_threads", "gmail_search_threads"),
        ("outlook_", "get_message", "outlook_get_message"),
        ("", "list_labels", "list_labels"),
    ],
)
def test_convert_mcp_tool_schema(prefix, name, expected_name):
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    result = convert_mcp_tool_schema(build_tool(name, "does things", schema), prefix)
    assert result == {
        "name": expected_name,
        "description": "does things",
        "parameters": schema,
    }


def test_convert_mcp_tool_schema_defaults_missing_description_to_empty():
    result = convert_mcp_tool_schema(build_tool("t", description=None), "gmail_")
    assert result["description"] == ""


def test_register_mcp_tools_filters_to_allowlist():
    client = mock.create_autospec(McpClient, instance=True)
    client.list_tools.return_value = [
        build_tool("search_threads"),
        build_tool("create_draft"),
        build_tool("get_message"),
        build_tool("label_thread"),
    ]
    reg = ToolRegistry()

    count = register_mcp_tools(reg, client, "gmail_", {"search_threads", "get_message"})

    assert count == 2
    assert set(reg.registry) == {"gmail_search_threads", "gmail_get_message"}


def test_registered_tool_routes_to_client_with_unprefixed_name():
    client = mock.create_autospec(McpClient, instance=True)
    client.list_tools.return_value = [build_tool("search_threads")]
    client.call_tool.return_value = "thread results"
    reg = ToolRegistry()
    register_mcp_tools(reg, client, "gmail_", {"search_threads"})

    result = reg.call_tool("gmail_search_threads", {"query": "newer_than:7d"})

    assert result == "thread results"
    client.call_tool.assert_called_once_with(
        "search_threads", {"query": "newer_than:7d"}
    )


def test_register_mcp_tools_degrades_on_discovery_failure():
    client = mock.create_autospec(McpClient, instance=True)
    client.url = "http://localhost:8000/mcp"
    client.list_tools.side_effect = ConnectionError("server unreachable")
    reg = ToolRegistry()

    count = register_mcp_tools(reg, client, "gmail_", {"search_threads"})

    assert count == 0
    assert reg.registry == {}
