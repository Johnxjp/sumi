from src.config import app_config
from src.mcp_client import McpClient
from src.tools.mcp import register_mcp_tools
from src.tools.registry import ToolRegistry, registry

# Read-only tools exposed by workspace-mcp's gmail service. Excludes
# get_gmail_attachment_content (base64 payloads would flood the conversation
# history) and list_gmail_filters (needs the settings scope).
GMAIL_READ_TOOLS = {
    "search_gmail_messages",
    "get_gmail_message_content",
    "get_gmail_messages_content_batch",
    "get_gmail_thread_content",
    "get_gmail_threads_content_batch",
    "list_gmail_labels",
}


def register_gmail_tools(reg: ToolRegistry = registry) -> int:
    client = McpClient(app_config.gmail_mcp_url)
    return register_mcp_tools(reg, client, "", GMAIL_READ_TOOLS)
