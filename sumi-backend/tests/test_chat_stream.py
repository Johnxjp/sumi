import asyncio
import json
import logging
from collections.abc import AsyncIterator
from unittest import mock

import logfire
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from src.agent import Agent, TextDelta, ToolCall
from src.chat.stream import parse_arguments, stream_reply


def decode_frames(frames: list[str]) -> list[dict]:
    for frame in frames:
        assert frame.startswith("data: ") and frame.endswith("\n\n")
    return [json.loads(frame[len("data: ") : -2]) for frame in frames]


def collect(frames: AsyncIterator[str]) -> list[str]:
    """Drains the async generator on a throwaway event loop, as the server would."""

    async def drain() -> list[str]:
        return [frame async for frame in frames]

    return asyncio.run(drain())


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ('{"query": "q"}', {"query": "q"}),
        ('{"query": ', {}),
        ("[1, 2]", {}),
    ],
)
def test_parse_arguments(arguments, expected):
    assert parse_arguments(arguments) == expected


def test_stream_reply_encodes_each_event_then_done():
    agent = mock.create_autospec(Agent, instance=True)
    agent.stream.return_value = iter(
        [
            ToolCall("search_notes", '{"query": "q"}'),
            TextDelta("ans"),
            TextDelta("wer\n"),
        ]
    )

    frames = collect(stream_reply(agent, tools=[{"tool": 1}], message="question"))

    assert decode_frames(frames) == [
        {"type": "tool_call", "name": "search_notes", "arguments": {"query": "q"}},
        {"type": "text", "text": "ans"},
        {"type": "text", "text": "wer\n"},
        {"type": "done"},
    ]
    agent.stream.assert_called_once_with("question", [{"tool": 1}])


def test_stream_reply_reports_a_failure_as_an_error_event_instead_of_done(caplog):
    agent = mock.create_autospec(Agent, instance=True)

    def events(message, tools):
        yield TextDelta("partial")
        raise RuntimeError("model error: rate limited")

    agent.stream.side_effect = events

    frames = collect(stream_reply(agent, tools=[], message="question"))

    assert decode_frames(frames) == [
        {"type": "text", "text": "partial"},
        {"type": "error", "message": "RuntimeError: model error: rate limited"},
    ]
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.exc_info[0] is RuntimeError


def test_streaming_response_keeps_the_agents_spans_in_one_trace(capfire):
    """Guards the single worker thread: a span held open across a yield must stay the parent."""
    agent = mock.create_autospec(Agent, instance=True)

    def events(message, tools):
        with logfire.span("invoke_agent sumi"):
            yield TextDelta("a")
            with logfire.span("chat model"):
                pass
            yield TextDelta("b")

    agent.stream.side_effect = events

    app = FastAPI()

    @app.post("/chat")
    def chat() -> StreamingResponse:
        return StreamingResponse(
            stream_reply(agent, [], "question"), media_type="text/event-stream"
        )

    body = TestClient(app).post("/chat").text

    frames = [f"{chunk}\n\n" for chunk in body.split("\n\n") if chunk]
    assert decode_frames(frames) == [
        {"type": "text", "text": "a"},
        {"type": "text", "text": "b"},
        {"type": "done"},
    ]
    spans = {span["name"]: span for span in capfire.exporter.exported_spans_as_dict()}
    assert (
        spans["chat model"]["parent"]["span_id"]
        == spans["invoke_agent sumi"]["context"]["span_id"]
    )
    assert (
        spans["chat model"]["parent"]["trace_id"]
        == spans["invoke_agent sumi"]["context"]["trace_id"]
    )
