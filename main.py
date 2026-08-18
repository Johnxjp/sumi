"""Main agent loop"""

from src.agent import Agent
from src.config import app_config
from src.tool_registry import registry


def main():
    print("Hello from sumi-backend!")
    agent = Agent(
        api_key=app_config.api_key,
        model=app_config.model_name,
        system_prompt="You are a helpful assistant that can read files and list directories. "
        "You have access to a directory of the user's notes."
        "The root path is '.' and everything is relative to it. "
        "You do not have permission to access files outside of the root path. "
        "You can read text files but not binary files at this time.",
    )

    query = ""
    while query.lower() != "exit":
        query = input("Enter your query: ").strip()
        result = agent.run(query=query, tools=registry.tools)
        print("RESULTS")
        print(result)


if __name__ == "__main__":
    main()
