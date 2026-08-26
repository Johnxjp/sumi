from unittest import mock

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from src.mcp_client import McpClient


def build_result(texts: list[str], is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=t) for t in texts], isError=is_error
    )


def configure_session(mock_client_cls: mock.MagicMock) -> mock.AsyncMock:
    session = mock.AsyncMock()
    mock_client_cls.return_value.__aenter__.return_value = session
    mock_client_cls.return_value.__aexit__.return_value = False
    return session


@mock.patch("src.mcp_client.Client")
@mock.patch("src.mcp_client.create_mcp_http_client", autospec=True)
@mock.patch("src.mcp_client.streamable_http_client", autospec=True)
def test_list_tools_returns_tools_with_bearer_header(
    mock_transport, mock_http, mock_client_cls
):
    session = configure_session(mock_client_cls)
    tools = [Tool(name="search_threads", inputSchema={"type": "object"})]
    session.list_tools.return_value = mock.Mock(tools=tools)
    client = McpClient("https://example.com/mcp", get_token=lambda: "tok-123")

    assert client.list_tools() == tools
    mock_http.assert_called_once_with(headers={"Authorization": "Bearer tok-123"})
    mock_transport.assert_called_once_with(
        "https://example.com/mcp", http_client=mock_http.return_value
    )


@mock.patch("src.mcp_client.Client")
@mock.patch("src.mcp_client.create_mcp_http_client", autospec=True)
@mock.patch("src.mcp_client.streamable_http_client", autospec=True)
def test_list_tools_sends_no_auth_header_without_token(
    mock_transport, mock_http, mock_client_cls
):
    session = configure_session(mock_client_cls)
    session.list_tools.return_value = mock.Mock(tools=[])
    client = McpClient("http://localhost:8000/mcp")

    assert client.list_tools() == []
    mock_http.assert_called_once_with(headers=None)


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (["only block"], "only block"),
        (["first", "second"], "first\nsecond"),
        ([], ""),
    ],
)
@mock.patch("src.mcp_client.Client")
@mock.patch("src.mcp_client.create_mcp_http_client", autospec=True)
@mock.patch("src.mcp_client.streamable_http_client", autospec=True)
def test_call_tool_flattens_text_content(
    mock_transport, mock_http, mock_client_cls, texts, expected
):
    session = configure_session(mock_client_cls)
    session.call_tool.return_value = build_result(texts)
    client = McpClient("https://example.com/mcp", get_token=lambda: "tok")

    assert client.call_tool("list_labels", {}) == expected
    session.call_tool.assert_awaited_once_with("list_labels", {})


@pytest.mark.parametrize(
    ("texts", "match"),
    [
        (["quota exceeded"], "quota exceeded"),
        ([], "returned an error"),
    ],
)
@mock.patch("src.mcp_client.Client")
@mock.patch("src.mcp_client.create_mcp_http_client", autospec=True)
@mock.patch("src.mcp_client.streamable_http_client", autospec=True)
def test_call_tool_raises_on_error_result(
    mock_transport, mock_http, mock_client_cls, texts, match
):
    session = configure_session(mock_client_cls)
    session.call_tool.return_value = build_result(texts, is_error=True)
    client = McpClient("https://example.com/mcp", get_token=lambda: "tok")

    with pytest.raises(RuntimeError, match=match):
        client.call_tool("search_threads", {"query": "x"})
