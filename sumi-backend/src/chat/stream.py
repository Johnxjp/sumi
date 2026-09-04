"""Turns the agent's events into server-sent events (SSE) for the browser."""

import json
import logging
from collections.abc import Iterator
from typing import Any

from src.agent import Agent, AgentEvent, TextDelta

logger = logging.getLogger(__name__)


def encode_event(payload: dict[str, Any]) -> str:
    """One SSE frame: a `data:` line holding the JSON payload, ended by a blank line."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def parse_arguments(arguments: str) -> dict[str, Any]:
    """The model's tool arguments as an object, or {} when they are not a JSON object."""
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_payload(event: AgentEvent) -> dict[str, Any]:
    if isinstance(event, TextDelta):
        return {"type": "text", "text": event.text}
    return {
        "type": "tool_call",
        "name": event.name,
        "arguments": parse_arguments(event.arguments),
    }


def stream_reply(
    agent: Agent, tools: list[dict[str, Any]], message: str
) -> Iterator[str]:
    """SSE frames for one user message: text and tool_call events, then done — or error if the agent fails."""
    try:
        for event in agent.stream(message, tools):
            yield encode_event(build_payload(event))
    except Exception as exc:
        logger.exception("Reply failed for message %r", message)
        yield encode_event({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        return
    yield encode_event({"type": "done"})
