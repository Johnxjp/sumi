"""Dispatch a tool call from the model to the registry and format the result."""

import json
from typing import Any

from src.tools.registry import registry


def run_tool(name: str, arguments: str) -> tuple[bool, Any]:
    """Returns (success, result) where success is True if the tool ran successfully, and result is the tool's output or error message."""
    try:
        arguments = json.loads(arguments)
        return True, registry.call_tool(name, arguments)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def stringify_tool_result(tool_results: str | list[str]) -> str:
    if isinstance(tool_results, str):
        return tool_results
    return "\n".join(tool_results)
