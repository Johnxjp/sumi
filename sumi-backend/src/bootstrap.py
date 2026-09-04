"""Builds the agent with every tool registered: shared by the terminal REPL and the web chat."""

import src.tools.file  # noqa: F401  # registers the filesystem tools on import
from src.agent import Agent
from src.config import app_config
from src.tools.gmail import register_gmail_tools
from src.tools.search import register_search_tools

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions from the user's personal "
    "notes (from Notion) and, when the tools are present, their Gmail. "
    "Choosing a tool: use search_notes when the request needs an answer to a "
    "question or information found by similarity; use grep when the user wants "
    "specific terms found in a title or note; use read_file, with a chunk's "
    "'path', when a chunk is cut off or the whole note is needed; use "
    "get_directory_listing to browse folders. "
    "Before searching, work out what the user actually wants and search for that: "
    "'What makes Elon Musk successful?' may become 'Elon Musk behaviours' or "
    "'Elon Musk reasons for success'. When a request has several parts, run "
    "several searches: 'What does Elon Musk have in common with Obama?' becomes "
    "'Elon Musk personality' and 'Barack Obama personality'. Tell the user how "
    "you interpreted their request whenever you changed it. "
    "Paths are relative to the notes root '.'. You cannot access anything outside "
    "it, and you can read text files but not binary files. "
    "When an answer comes from the notes, name the note (by title) it came from. "
    "Read-only Gmail tools (search_gmail_messages, get_gmail_message_content and "
    "similar) may also be available."
)


def register_tools() -> int:
    """Registers the note-search and Gmail tools; returns how many Gmail tools the MCP server offered (0 when it is not running)."""
    register_search_tools()
    return register_gmail_tools()


def build_agent(verbose: bool = False) -> Agent:
    return Agent(
        api_key=app_config.api_key,
        model=app_config.model_name,
        system_prompt=SYSTEM_PROMPT,
        verbose=verbose,
    )
