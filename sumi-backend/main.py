"""Main agent loop"""

import argparse

from src.bootstrap import build_agent, register_tools
from src.notion.sync import describe_index_staleness
from src.tools.registry import registry


def main():
    parser = argparse.ArgumentParser(description="Sumi terminal agent")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print intermediate output (model reasoning and tool calls)",
    )
    args = parser.parse_args()

    print("Hello from sumi-backend!")
    staleness = describe_index_staleness()
    if staleness:
        print(f"[info] {staleness}")
    n_gmail_tools = register_tools()
    if n_gmail_tools:
        print(f"[info] Registered {n_gmail_tools} read-only Gmail tools.")
    agent = build_agent(verbose=args.verbose)

    query = ""
    while query.lower() != "exit":
        query = input("Enter your query: ").strip()
        result = agent.run(query=query, tools=registry.tools)
        print("RESULTS")
        print(result)


if __name__ == "__main__":
    main()
