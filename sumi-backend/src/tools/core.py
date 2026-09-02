"""Dispatch a tool call from the model to the registry and format the result."""

import json
from typing import Any

from src.tools.registry import registry


def run_tool(name: str, arguments: str) -> tuple[bool, Any]:
    """Returns (success, result) where success is True if the tool ran successfully, and result is the tool's output or error message."""
    try:
        arguments = json.loads(arguments)
        return True, registry.call_tool(name, arguments)
    except Exception as e:  # noqa: BLE001 - tool errors go back to the model as text
        return False, f"{type(e).__name__}: {e}"


def stringify_tool_result(tool_results: Any) -> str:
    if isinstance(tool_results, str):
        return tool_results
    if isinstance(tool_results, list) and all(
        isinstance(item, str) for item in tool_results
    ):
        return "\n".join(tool_results)
    return json.dumps(tool_results, ensure_ascii=False)
