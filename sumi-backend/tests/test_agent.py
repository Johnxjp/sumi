from types import SimpleNamespace
from unittest import mock

from src.agent import Agent


def make_tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def make_response(
    finish_reason: str, content: str | None = None, tool_calls: list | None = None
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, reasoning=None, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish_reason, message=message)]
    )


@mock.patch("src.agent.summarise_tool_result", autospec=True)
@mock.patch("src.agent.run_tool", autospec=True)
def test_run_replaces_summarised_results_once_the_turn_ends(run_tool, summarise):
    run_tool.side_effect = [(True, [{"rank": 1}]), (True, "note text"), (False, "boom")]
    summarise.side_effect = lambda name, arguments, result: (
        "stub" if name == "search_notes" else None
    )
    responses = iter(
        [
            make_response(
                "tool_calls",
                tool_calls=[
                    make_tool_call("c1", "search_notes", '{"query": "q"}'),
                    make_tool_call("c2", "read_file", '{"filename": "a.md"}'),
                    make_tool_call("c3", "grep", '{"pattern": "x"}'),
                ],
            ),
            make_response("stop", content="answer"),
        ]
    )
    agent = Agent(api_key="key", model="model", system_prompt="sys")
    agent.client = SimpleNamespace(
        chat=SimpleNamespace(send=lambda **kwargs: next(responses))
    )

    assert agent.run("question", tools=[]) == "answer"

    tool_messages = [
        m
        for m in agent.conversation_history
        if isinstance(m, dict) and m.get("role") == "tool"
    ]
    assert tool_messages == [
        {"role": "tool", "tool_call_id": "c1", "content": "stub"},
        {"role": "tool", "tool_call_id": "c2", "content": "note text"},
        {"role": "tool", "tool_call_id": "c3", "content": "Error: boom"},
    ]
    assert summarise.call_args_list == [
        mock.call("search_notes", '{"query": "q"}', [{"rank": 1}]),
        mock.call("read_file", '{"filename": "a.md"}', "note text"),
    ]
