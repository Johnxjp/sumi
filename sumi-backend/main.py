"""Main agent loop"""

import src.tools.file  # noqa: F401  # registers the filesystem tools on import
from src.agent import Agent
from src.config import app_config
from src.tools.gmail import register_gmail_tools
from src.tools.registry import registry
from src.tools.search import register_search_tools

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions from the user's personal "
    "notes (a Notion export) and, when the tools are present, their Gmail. "
    "To answer a question about the notes: "
    "1. Call search_notes first with a natural-language query. It returns the "
    "best-matching chunks of notes ordered by rank; some may not be relevant, so "
    "judge each by its content. "
    "2. If a chunk is cut off or you need the whole note, call read_file with the "
    "chunk's 'source' path. "
    "3. Use grep only to find an exact title or string, and get_directory_listing "
    "to browse folders. "
    "Paths are relative to the notes root '.'. You cannot access anything outside "
    "it, and you can read text files but not binary files. "
    "When an answer comes from the notes, name the note (by title) it came from. "
    "Read-only Gmail tools (search_gmail_messages, get_gmail_message_content and "
    "similar) may also be available."
)


def main():
    print("Hello from sumi-backend!")
    register_search_tools()
    n_gmail_tools = register_gmail_tools()
    if n_gmail_tools:
        print(f"[info] Registered {n_gmail_tools} read-only Gmail tools.")
    agent = Agent(
        api_key=app_config.api_key,
        model=app_config.model_name,
        system_prompt=SYSTEM_PROMPT,
    )

    query = ""
    while query.lower() != "exit":
        query = input("Enter your query: ").strip()
        result = agent.run(query=query, tools=registry.tools)
        print("RESULTS")
        print(result)


if __name__ == "__main__":
    main()
