from unittest import mock

import pytest

from src.tools.core import run_tool, stringify_tool_result, summarise_tool_result


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ("plain", "plain"),
        (["a.md", "b.md"], "a.md\nb.md"),
        ([{"rank": 1, "text": "café"}], '[{"rank": 1, "text": "café"}]'),
    ],
)
def test_stringify_tool_result(result, expected):
    assert stringify_tool_result(result) == expected


@mock.patch("src.tools.core.registry", autospec=True)
def test_summarise_tool_result_parses_arguments_and_delegates(registry):
    registry.summarise_result.return_value = "stub"

    assert summarise_tool_result("search_notes", '{"query": "q"}', ["row"]) == "stub"
    registry.summarise_result.assert_called_once_with(
        "search_notes", {"query": "q"}, ["row"]
    )


@mock.patch("src.tools.core.registry", autospec=True)
def test_run_tool_traces_a_successful_call(registry, capfire):
    registry.call_tool.return_value = ["a.md", "b.md"]

    assert run_tool("list_directory", '{"path": "."}') == (True, ["a.md", "b.md"])

    [span] = capfire.exporter.exported_spans_as_dict()
    assert span["name"] == "execute_tool {gen_ai.tool.name}"
    assert span["attributes"]["gen_ai.tool.name"] == "list_directory"
    assert span["attributes"]["gen_ai.tool.call.arguments"] == '{"path": "."}'
    assert span["attributes"]["gen_ai.tool.call.result"] == "a.md\nb.md"
    assert span["attributes"]["success"] is True


@mock.patch("src.tools.core.registry", autospec=True)
def test_run_tool_traces_a_failure_as_the_span_result(registry, capfire):
    registry.call_tool.side_effect = ValueError("unknown tool: nope")

    assert run_tool("nope", "{}") == (False, "ValueError: unknown tool: nope")

    [span] = capfire.exporter.exported_spans_as_dict()
    assert span["attributes"]["success"] is False
    assert (
        span["attributes"]["gen_ai.tool.call.result"]
        == "ValueError: unknown tool: nope"
    )
