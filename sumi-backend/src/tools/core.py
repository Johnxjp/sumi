"""Dispatch a tool call from the model to the registry and format the result."""

import json
from typing import Any

import logfire

from src.observability import trim_chunk_text, truncate
from src.tools.registry import registry


def run_tool(name: str, arguments: str) -> tuple[bool, Any]:
    """Returns (success, result) where success is True if the tool ran successfully, and result is the tool's output or error message."""
    with logfire.span(
        "execute_tool {gen_ai.tool.name}",
        **{
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": name,
            "gen_ai.tool.call.arguments": arguments,
        },
    ) as span:
        try:
            result = registry.call_tool(name, json.loads(arguments))
        except Exception as e:  # noqa: BLE001 - tool errors go back to the model as text
            message = f"{type(e).__name__}: {e}"
            span.set_attribute("gen_ai.tool.call.result", message)
            span.set_attribute("success", False)
            return False, message
        span.set_attribute(
            "gen_ai.tool.call.result",
            truncate(stringify_tool_result(trim_chunk_text(result))),
        )
        span.set_attribute("success", True)
        return True, result


def summarise_tool_result(name: str, arguments: str, result: Any) -> str | None:
    """A short stand-in for the result, or None if the tool keeps its full result in history."""
    return registry.summarise_result(name, json.loads(arguments), result)


def stringify_tool_result(tool_results: Any) -> str:
    if isinstance(tool_results, str):
        return tool_results
    if isinstance(tool_results, list) and all(
        isinstance(item, str) for item in tool_results
    ):
        return "\n".join(tool_results)
    return json.dumps(tool_results, ensure_ascii=False)
