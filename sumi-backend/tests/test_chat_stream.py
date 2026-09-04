import json
import logging
from unittest import mock

import pytest

from src.agent import Agent, TextDelta, ToolCall
from src.chat.stream import parse_arguments, stream_reply


def decode_frames(frames: list[str]) -> list[dict]:
    for frame in frames:
        assert frame.startswith("data: ") and frame.endswith("\n\n")
    return [json.loads(frame[len("data: ") : -2]) for frame in frames]


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

    frames = list(stream_reply(agent, tools=[{"tool": 1}], message="question"))

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

    frames = list(stream_reply(agent, tools=[], message="question"))

    assert decode_frames(frames) == [
        {"type": "text", "text": "partial"},
        {"type": "error", "message": "RuntimeError: model error: rate limited"},
    ]
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.exc_info[0] is RuntimeError
