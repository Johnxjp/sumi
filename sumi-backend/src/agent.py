"""OpenRouter tool-calling agent, consumed as a stream of events."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import logfire
from openrouter import OpenRouter

from src.observability import build_genai_messages
from src.tools.core import run_tool, stringify_tool_result, summarise_tool_result
from src.usage import current_user_query


@dataclass(frozen=True)
class TextDelta:
    """A piece of the assistant's reply, in the order the model produced it."""

    text: str


@dataclass(frozen=True)
class ToolCall:
    """The model asked for a tool; emitted just before the tool runs."""

    name: str
    arguments: str


AgentEvent = TextDelta | ToolCall


class StreamedTurn:
    """Folds the chunks of one streamed model response into the message to keep in the history."""

    def __init__(self) -> None:
        self.content: list[str] = []
        self.reasoning: list[str] = []
        self.tool_calls: dict[int, dict[str, str]] = {}
        self.finish_reason: str | None = None
        self.usage: Any = None

    def add(self, chunk: Any) -> str:
        """Folds one chunk in and returns the reply text it carried, if any."""
        if chunk.error is not None:
            raise RuntimeError(f"model error: {chunk.error.message}")
        # OpenRouter sends token counts on the final chunk, which carries no choices.
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self.usage = usage
        if not chunk.choices:
            return ""
        choice = chunk.choices[0]
        if choice.finish_reason:
            self.finish_reason = choice.finish_reason
        delta = choice.delta
        if isinstance(delta.reasoning, str):
            self.reasoning.append(delta.reasoning)
        for call in delta.tool_calls or []:
            entry = self.tool_calls.setdefault(
                call.index, {"id": "", "name": "", "arguments": ""}
            )
            if call.id:
                entry["id"] = call.id
            if call.function and call.function.name:
                entry["name"] = call.function.name
            if call.function and call.function.arguments:
                entry["arguments"] += call.function.arguments
        text = delta.content if isinstance(delta.content, str) else ""
        self.content.append(text)
        return text

    def build_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(self.content) or None,
        }
        if self.reasoning:
            message["reasoning"] = "".join(self.reasoning)
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": call["arguments"]},
                }
                for _, call in sorted(self.tool_calls.items())
            ]
        return message


def record_chat_response(
    span: logfire.LogfireSpan, turn: StreamedTurn, message: dict[str, Any]
) -> None:
    """Puts the model's reply, stop reason and token counts on the chat span."""
    _, output_messages = build_genai_messages([message])
    span.set_attribute("gen_ai.output.messages", output_messages)
    if turn.finish_reason:
        span.set_attribute("gen_ai.response.finish_reasons", [turn.finish_reason])
    if turn.reasoning:
        span.set_attribute("reasoning", "".join(turn.reasoning))
    if turn.usage is not None:
        span.set_attribute("gen_ai.usage.input_tokens", turn.usage.prompt_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", turn.usage.completion_tokens)


class Agent:
    def __init__(
        self,
        api_key: str,
        model: str,
        system_prompt: str = "",
        verbose: bool = False,
    ):
        self.conversation_history: list = []
        self.model = model
        self.api_key = api_key
        self.client = None
        self.system_prompt = system_prompt
        self.verbose = verbose
        self.client = OpenRouter(api_key)

        self.clear_conversation_history()

    def _log(self, message: str) -> None:
        if self.verbose:
            print(message, flush=True)

    def clear_conversation_history(self):
        self.conversation_history = []
        self.conversation_history.append(
            {"role": "system", "content": self.system_prompt}
        )

    def run(
        self,
        query: str,
        tools: list[dict[str, Any]],
        max_iterations: int = 10,
    ) -> str:
        """Answers `query` and returns the reply: the text produced after the last tool call."""
        reply: list[str] = []
        for event in self.stream(query, tools, max_iterations):
            if isinstance(event, ToolCall):
                reply.clear()
            else:
                reply.append(event.text)
        return "".join(reply)

    def stream(
        self,
        query: str,
        tools: list[dict[str, Any]],
        max_iterations: int = 10,
    ) -> Iterator[AgentEvent]:
        """Answers `query`, yielding reply text as the model produces it and each tool call before it runs.

        If the model or a tool call fails, the whole exchange is dropped from the
        history so the next query starts from a consistent state.
        """
        history_before = len(self.conversation_history)
        self.conversation_history.append({"role": "user", "content": query})
        # The search tool logs both queries, and only the agent's reaches it.
        user_query_token = current_user_query.set(query)
        # Tool results with a registered summariser are replaced by its short
        # stand-in once the turn ends, so they are not re-sent on every later call.
        stubs: list[tuple[dict[str, Any], str]] = []

        try:
            with logfire.span(
                "invoke_agent sumi",
                **{
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.agent.name": "sumi",
                },
            ):
                for _ in range(max_iterations):
                    instructions, input_messages = build_genai_messages(
                        self.conversation_history
                    )
                    turn = StreamedTurn()
                    with logfire.span(
                        "chat {gen_ai.request.model}",
                        **{
                            "gen_ai.operation.name": "chat",
                            "gen_ai.provider.name": "openrouter",
                            "gen_ai.request.model": self.model,
                            "gen_ai.system_instructions": instructions,
                            "gen_ai.input.messages": input_messages,
                        },
                    ) as span:
                        chunks = self.client.chat.send(
                            model=self.model,
                            messages=self.conversation_history,
                            tools=tools,
                            stream=True,
                        )
                        for chunk in chunks:
                            text = turn.add(chunk)
                            if text:
                                yield TextDelta(text)
                        message = turn.build_message()
                        record_chat_response(span, turn, message)
                    self._log(
                        f"[info] Model turn: finish_reason={turn.finish_reason}, "
                        f"text={len(''.join(turn.content))} chars, "
                        f"tool_calls={len(turn.tool_calls)}, "
                        f"reasoning: {''.join(turn.reasoning)}"
                    )

                    if turn.tool_calls:
                        self.conversation_history.append(message)
                        for call in message["tool_calls"]:
                            name = call["function"]["name"]
                            arguments = call["function"]["arguments"]
                            yield ToolCall(name, arguments)
                            self._log(f"[tool call] {name}({arguments})")
                            is_success, output = run_tool(name, arguments)
                            output_str = stringify_tool_result(output)
                            tool_message = {
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": output_str
                                if is_success
                                else f"Error: {output_str}",
                            }
                            self.conversation_history.append(tool_message)
                            if is_success:
                                stub = summarise_tool_result(name, arguments, output)
                                if stub is not None:
                                    stubs.append((tool_message, stub))
                    elif turn.finish_reason == "length":
                        # Basic Compaction
                        self._log(
                            "[info] Model response length exceeded. Compacting conversation history."
                        )
                        last_messages = self.conversation_history[
                            -5:
                        ]  # Keep last 5 messages
                        self.clear_conversation_history()
                        self.conversation_history.extend(last_messages)
                    else:
                        self.conversation_history.append(message)
                        return
        except Exception:
            del self.conversation_history[history_before:]
            raise
        finally:
            current_user_query.reset(user_query_token)
            for tool_message, stub in stubs:
                tool_message["content"] = stub
