import json
from types import SimpleNamespace
from unittest import mock

import pytest

from src.agent import Agent, TextDelta, ToolCall


def make_tool_call_delta(
    index: int,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def make_chunk(
    content: str | None = None,
    reasoning: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
    error: SimpleNamespace | None = None,
) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, reasoning=reasoning, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)], error=error
    )


USAGE_CHUNK = SimpleNamespace(choices=[], error=None)


def make_agent(turns: list[list[SimpleNamespace]], verbose: bool = False) -> Agent:
    """An agent whose model replies with the given streamed turns, one chunk list per call."""
    responses = iter(turns)
    agent = Agent(api_key="key", model="model", system_prompt="sys", verbose=verbose)
    agent.client = SimpleNamespace(
        chat=SimpleNamespace(send=lambda **kwargs: iter(next(responses)))
    )
    return agent


def tool_messages(agent: Agent) -> list[dict]:
    return [
        m
        for m in agent.conversation_history
        if isinstance(m, dict) and m.get("role") == "tool"
    ]


@mock.patch("src.agent.summarise_tool_result", autospec=True)
@mock.patch("src.agent.run_tool", autospec=True)
def test_run_replaces_summarised_results_once_the_turn_ends(run_tool, summarise):
    run_tool.side_effect = [(True, [{"rank": 1}]), (True, "note text"), (False, "boom")]
    summarise.side_effect = lambda name, arguments, result: (
        "stub" if name == "search_notes" else None
    )
    agent = make_agent(
        [
            [
                make_chunk(
                    tool_calls=[
                        make_tool_call_delta(0, "c1", "search_notes", '{"query": "q"}'),
                        make_tool_call_delta(
                            1, "c2", "read_file", '{"filename": "a.md"}'
                        ),
                        make_tool_call_delta(2, "c3", "grep", '{"pattern": "x"}'),
                    ],
                    finish_reason="tool_calls",
                )
            ],
            [make_chunk(content="answer", finish_reason="stop")],
        ]
    )

    assert agent.run("question", tools=[]) == "answer"

    assert tool_messages(agent) == [
        {"role": "tool", "tool_call_id": "c1", "content": "stub"},
        {"role": "tool", "tool_call_id": "c2", "content": "note text"},
        {"role": "tool", "tool_call_id": "c3", "content": "Error: boom"},
    ]
    assert summarise.call_args_list == [
        mock.call("search_notes", '{"query": "q"}', [{"rank": 1}]),
        mock.call("read_file", '{"filename": "a.md"}', "note text"),
    ]


@mock.patch("src.agent.summarise_tool_result", autospec=True)
@mock.patch("src.agent.run_tool", autospec=True)
def test_run_prints_nothing_when_not_verbose(run_tool, summarise, capsys):
    run_tool.return_value = (True, "note text")
    summarise.return_value = None
    agent = make_agent(
        [
            [
                make_chunk(
                    tool_calls=[
                        make_tool_call_delta(
                            0, "c1", "read_file", '{"filename": "a.md"}'
                        )
                    ],
                    finish_reason="tool_calls",
                )
            ],
            [make_chunk(content="answer", finish_reason="stop")],
        ],
        verbose=False,
    )

    assert agent.run("question", tools=[]) == "answer"
    assert capsys.readouterr().out == ""


@mock.patch("src.agent.summarise_tool_result", autospec=True)
@mock.patch("src.agent.run_tool", autospec=True)
def test_stream_yields_text_as_it_arrives_and_each_tool_call_before_it_runs(
    run_tool, summarise
):
    run_tool.return_value = (True, "result")
    summarise.return_value = None
    events: list = []
    run_tool.side_effect = lambda name, arguments: (
        events.append(f"ran {name}")
        or (
            True,
            "result",
        )
    )
    agent = make_agent(
        [
            [
                make_chunk(reasoning="thinking "),
                make_chunk(
                    content="Let me look. ",
                    tool_calls=[make_tool_call_delta(0, "c1", "search_notes", '{"que')],
                ),
                make_chunk(
                    tool_calls=[
                        make_tool_call_delta(0, arguments='ry": "q"}'),
                        make_tool_call_delta(1, "c2", "grep", '{"pattern": "x"}'),
                    ],
                    finish_reason="tool_calls",
                ),
                USAGE_CHUNK,
            ],
            [
                make_chunk(content="ans"),
                make_chunk(content="wer", finish_reason="stop"),
                USAGE_CHUNK,
            ],
        ]
    )

    for event in agent.stream("question", tools=[]):
        events.append(event)  # noqa: PERF402 - run_tool appends to `events` too, so order must be observed live

    assert events == [
        TextDelta("Let me look. "),
        ToolCall("search_notes", '{"query": "q"}'),
        "ran search_notes",
        ToolCall("grep", '{"pattern": "x"}'),
        "ran grep",
        TextDelta("ans"),
        TextDelta("wer"),
    ]
    assert agent.conversation_history[2] == {
        "role": "assistant",
        "content": "Let me look. ",
        "reasoning": "thinking ",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "search_notes", "arguments": '{"query": "q"}'},
            },
            {
                "id": "c2",
                "type": "function",
                "function": {"name": "grep", "arguments": '{"pattern": "x"}'},
            },
        ],
    }
    assert agent.conversation_history[-1] == {"role": "assistant", "content": "answer"}


@mock.patch("src.agent.summarise_tool_result", autospec=True)
@mock.patch("src.agent.run_tool", autospec=True)
def test_run_returns_only_the_text_after_the_last_tool_call(run_tool, summarise):
    run_tool.return_value = (True, "result")
    summarise.return_value = None
    agent = make_agent(
        [
            [
                make_chunk(
                    content="Let me look.",
                    tool_calls=[make_tool_call_delta(0, "c1", "grep", "{}")],
                    finish_reason="tool_calls",
                )
            ],
            [make_chunk(content="answer", finish_reason="stop")],
        ]
    )

    assert agent.run("question", tools=[]) == "answer"


def test_stream_drops_the_exchange_from_history_when_the_model_fails():
    agent = Agent(api_key="key", model="model", system_prompt="sys")
    agent.conversation_history.append({"role": "user", "content": "earlier"})
    history_before = list(agent.conversation_history)

    def fail(**kwargs):
        raise ConnectionError("down")

    agent.client = SimpleNamespace(chat=SimpleNamespace(send=fail))

    with pytest.raises(ConnectionError):
        list(agent.stream("question", tools=[]))

    assert agent.conversation_history == history_before


def test_stream_raises_when_a_chunk_carries_an_error():
    agent = make_agent(
        [
            [
                make_chunk(content="partial"),
                make_chunk(error=SimpleNamespace(code=429, message="rate limited")),
            ]
        ]
    )

    with pytest.raises(RuntimeError, match="rate limited"):
        list(agent.stream("question", tools=[]))

    assert agent.conversation_history == [{"role": "system", "content": "sys"}]


def test_stream_compacts_history_when_the_reply_is_cut_off():
    agent = make_agent(
        [
            [make_chunk(content="too long", finish_reason="length")],
            [make_chunk(content="answer", finish_reason="stop")],
        ]
    )
    for i in range(6):
        agent.conversation_history.append({"role": "user", "content": f"old {i}"})

    events = list(agent.stream("question", tools=[]))

    assert events == [TextDelta("too long"), TextDelta("answer")]
    assert agent.conversation_history == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old 2"},
        {"role": "user", "content": "old 3"},
        {"role": "user", "content": "old 4"},
        {"role": "user", "content": "old 5"},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]


@mock.patch("src.agent.summarise_tool_result", autospec=True)
@mock.patch("src.agent.run_tool", autospec=True)
def test_stream_traces_the_run_as_one_agent_span_over_a_chat_span_per_turn(
    run_tool, summarise, capfire
):
    run_tool.return_value = (True, "note text")
    summarise.return_value = None
    agent = make_agent(
        [
            [
                make_chunk(
                    tool_calls=[
                        make_tool_call_delta(
                            0, "c1", "read_file", '{"filename": "a.md"}'
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                SimpleNamespace(
                    choices=[],
                    error=None,
                    usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
                ),
            ],
            [make_chunk(content="answer", reasoning="thinking", finish_reason="stop")],
        ]
    )

    assert agent.run("question", tools=[]) == "answer"

    exported = capfire.exporter.exported_spans_as_dict()
    [run] = [span for span in exported if span["name"] == "invoke_agent sumi"]
    chats = [span for span in exported if span["name"] == "chat {gen_ai.request.model}"]

    assert run["attributes"]["gen_ai.agent.name"] == "sumi"
    assert run["attributes"]["gen_ai.operation.name"] == "invoke_agent"
    assert len(chats) == 2
    assert all(chat["parent"]["span_id"] == run["context"]["span_id"] for chat in chats)
    assert [
        json.loads(chat["attributes"]["gen_ai.response.finish_reasons"])
        for chat in chats
    ] == [["tool_calls"], ["stop"]]
    assert chats[0]["attributes"]["gen_ai.usage.input_tokens"] == 11
    assert chats[0]["attributes"]["gen_ai.usage.output_tokens"] == 22
    assert chats[1]["attributes"]["reasoning"] == "thinking"

    assert json.loads(chats[0]["attributes"]["gen_ai.system_instructions"]) == [
        {"type": "text", "content": "sys"}
    ]
    assert json.loads(chats[0]["attributes"]["gen_ai.input.messages"]) == [
        {"role": "user", "parts": [{"type": "text", "content": "question"}]}
    ]
    assert json.loads(chats[1]["attributes"]["gen_ai.input.messages"])[-1] == {
        "role": "tool",
        "parts": [{"type": "tool_call_response", "id": "c1", "response": "note text"}],
    }
    assert json.loads(chats[1]["attributes"]["gen_ai.output.messages"]) == [
        {"role": "assistant", "parts": [{"type": "text", "content": "answer"}]}
    ]
