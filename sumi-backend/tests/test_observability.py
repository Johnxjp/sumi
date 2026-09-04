import pytest

from src.observability import build_genai_messages, truncate


def test_build_genai_messages_splits_instructions_from_the_conversation():
    history = [
        {"role": "system", "content": "you are sumi"},
        {"role": "user", "content": "what did I write about pasta?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "search_notes",
                        "arguments": '{"query": "pasta"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "a note about pasta"},
        {"role": "assistant", "content": "You wrote about pasta."},
    ]

    instructions, messages = build_genai_messages(history)

    assert instructions == [{"type": "text", "content": "you are sumi"}]
    assert messages == [
        {
            "role": "user",
            "parts": [{"type": "text", "content": "what did I write about pasta?"}],
        },
        {
            "role": "assistant",
            "parts": [
                {
                    "type": "tool_call",
                    "id": "c1",
                    "name": "search_notes",
                    "arguments": {"query": "pasta"},
                }
            ],
        },
        {
            "role": "tool",
            "parts": [
                {
                    "type": "tool_call_response",
                    "id": "c1",
                    "response": "a note about pasta",
                }
            ],
        },
        {
            "role": "assistant",
            "parts": [{"type": "text", "content": "You wrote about pasta."}],
        },
    ]


def test_build_genai_messages_keeps_unparsable_tool_arguments_as_text():
    history = [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "c1",
                    "function": {"name": "search_notes", "arguments": '{"query": '},
                }
            ],
        }
    ]

    _, [message] = build_genai_messages(history)

    assert message["parts"][0]["arguments"] == '{"query": '


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("short", 10, "short"),
        ("exactly10!", 10, "exactly10!"),
        ("0123456789abc", 10, "0123456789… [3 more characters]"),
    ],
)
def test_truncate(text, limit, expected):
    assert truncate(text, limit) == expected
