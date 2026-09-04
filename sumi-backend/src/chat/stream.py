"""Turns the agent's events into server-sent events (SSE) for the browser."""

import contextlib
import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

import anyio
import anyio.from_thread
import anyio.to_thread

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


def build_frames(
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


async def stream_reply(
    agent: Agent, tools: list[dict[str, Any]], message: str
) -> AsyncIterator[str]:
    """The frames for one reply, with the whole agent run on a single worker thread.

    Starlette drives a sync generator with one `anyio.to_thread.run_sync` call
    per item, and every call copies the context afresh. A trace span the agent
    holds open across a `yield` would therefore not be the active context on the
    next item, and the spans beneath it would start traces of their own. One
    `run_sync` call for the whole reply is one copied context, so the spans nest.
    """
    send, receive = anyio.create_memory_object_stream[str](0)

    def produce() -> None:
        with contextlib.closing(build_frames(agent, tools, message)) as frames:
            for frame in frames:
                try:
                    anyio.from_thread.run(send.send, frame)
                except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                    return  # the browser went away; stop the agent

    async def run_producer() -> None:
        try:
            await anyio.to_thread.run_sync(produce)
        finally:
            send.close()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(run_producer)
        async with receive:
            async for frame in receive:
                yield frame
