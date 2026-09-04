"""Logfire setup, and the helpers that turn the agent's history into trace attributes.

The attribute shapes follow the OpenTelemetry GenAI semantic conventions, which
is what makes Logfire render a model call as a readable transcript.
"""

import json
from typing import Any

import logfire

from src.config import app_config

TOOL_RESULT_LIMIT = 10_000


def configure_logfire() -> None:
    """Points the Logfire SDK at the project named by LOGFIRE_API_KEY. An empty key sends nothing."""
    token = app_config.logfire_api_key
    logfire.configure(
        token=token or None,
        send_to_logfire=bool(token),
        service_name="sumi",
        console=False,
    )


def truncate(text: str, limit: int = TOOL_RESULT_LIMIT) -> str:
    """Caps `text` at `limit` characters, saying how many were dropped."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… [{len(text) - limit} more characters]"


def decode_arguments(arguments: str | None) -> Any:
    """Tool arguments as an object, falling back to the raw string when they are not valid JSON."""
    if arguments is None:
        return None
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments


def build_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    """The text and tool-call parts of one user or assistant message."""
    parts: list[dict[str, Any]] = []
    content = message.get("content")
    if content:
        parts.append({"type": "text", "content": content})
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        parts.append(
            {
                "type": "tool_call",
                "id": call.get("id"),
                "name": function.get("name"),
                "arguments": decode_arguments(function.get("arguments")),
            }
        )
    return parts


def build_genai_messages(
    history: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Splits an OpenAI-style history into (system instructions, messages) in the GenAI shape.

    System messages are returned separately because the conventions carry them
    in their own attribute rather than as part of the conversation.
    """
    instructions: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    for message in history:
        role = message.get("role")
        if role == "system":
            instructions.append(
                {"type": "text", "content": message.get("content") or ""}
            )
        elif role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "parts": [
                        {
                            "type": "tool_call_response",
                            "id": message.get("tool_call_id"),
                            "response": message.get("content"),
                        }
                    ],
                }
            )
        else:
            messages.append({"role": role, "parts": build_parts(message)})
    return instructions, messages
