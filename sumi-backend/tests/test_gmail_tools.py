from unittest import mock

from src.config import app_config
from src.tools.gmail import GMAIL_READ_TOOLS, register_gmail_tools
from src.tools.registry import ToolRegistry


@mock.patch("src.tools.gmail.register_mcp_tools", autospec=True, return_value=5)
@mock.patch("src.tools.gmail.McpClient", autospec=True)
def test_register_gmail_tools_delegates_with_read_allowlist(
    mock_client_cls, mock_register
):
    reg = ToolRegistry()

    assert register_gmail_tools(reg) == 5
    mock_client_cls.assert_called_once_with(app_config.gmail_mcp_url)
    mock_register.assert_called_once_with(
        reg, mock_client_cls.return_value, "", GMAIL_READ_TOOLS
    )
