import pytest

from src.tools.core import stringify_tool_result


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
