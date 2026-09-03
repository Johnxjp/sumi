from unittest import mock

import pytest

from src.tools.core import stringify_tool_result, summarise_tool_result


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
