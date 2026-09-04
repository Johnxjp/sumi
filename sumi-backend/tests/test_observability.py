import pytest

from src.observability import build_genai_messages, trim_chunk_text, truncate


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


def test_trim_chunk_text_shortens_the_text_and_keeps_the_rest():
    chunks = [
        {
            "rank": 1,
            "chunk_id": "a.md#0",
            "source": "a.md",
            "title": "A",
            "text": "x" * 250,
        },
        {
            "rank": 2,
            "chunk_id": "b.md#0",
            "source": "b.md",
            "title": "B",
            "text": "short",
        },
    ]

    trimmed = trim_chunk_text(chunks)

    assert trimmed[0]["text"] == "x" * 100 + "… [150 more characters]"
    assert trimmed[1]["text"] == "short"
    assert [chunk["chunk_id"] for chunk in trimmed] == ["a.md#0", "b.md#0"]
    assert [chunk["rank"] for chunk in trimmed] == [1, 2]
    assert chunks[0]["text"] == "x" * 250, "the caller's chunks must not be mutated"


@pytest.mark.parametrize(
    "result",
    ["a plain string", ["a.md", "b.md"], [{"rank": 1, "source": "a.md"}]],
)
def test_trim_chunk_text_leaves_results_without_chunk_text_alone(result):
    assert trim_chunk_text(result) == result
