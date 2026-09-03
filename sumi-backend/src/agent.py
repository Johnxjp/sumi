"""OpenRouter tool-calling agent that drives the terminal REPL."""

from typing import Any

from openrouter import OpenRouter

from src.tools.core import run_tool, stringify_tool_result, summarise_tool_result


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
            print(message)

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
        """

        TODO: Need to handle dangling tool calls and errors so can continue to operate after restart and API won't fail
        """
        turn = 0

        self.conversation_history.append({"role": "user", "content": query})
        # Tool results with a registered summariser are replaced by its short
        # stand-in once the turn ends, so they are not re-sent on every later call.
        stubs: list[tuple[dict[str, Any], str]] = []

        try:
            while turn < max_iterations:
                response = self.client.chat.send(
                    model=self.model,
                    messages=self.conversation_history,
                    tools=tools,
                    stream=False,
                )
                self._log(
                    f"[info] Model response finish reason: {response.choices[0].finish_reason}, content: {response.choices[0].message.reasoning}"
                )

                result = response.choices[0]
                if result.finish_reason == "stop":
                    self.conversation_history.append(result.message)
                    return result.message.content
                elif result.finish_reason == "tool_calls":
                    self.conversation_history.append(
                        result.message
                    )  # formatted correctly
                    for tool_call in result.message.tool_calls:
                        name = tool_call.function.name
                        arguments = tool_call.function.arguments
                        self._log(f"[tool call] {name}({arguments})")
                        is_success, output = run_tool(name, arguments)
                        output_str = stringify_tool_result(output)
                        message = {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": output_str
                            if is_success
                            else f"Error: {output_str}",
                        }
                        self.conversation_history.append(message)
                        if is_success:
                            stub = summarise_tool_result(name, arguments, output)
                            if stub is not None:
                                stubs.append((message, stub))
                elif result.finish_reason == "length":
                    # Basic Compaction
                    self._log(
                        "[info] Model response length exceeded. Compacting conversation history."
                    )
                    last_messages = self.conversation_history[
                        -5:
                    ]  # Keep last 5 messages
                    self.clear_conversation_history()
                    self.conversation_history.extend(last_messages)

                turn += 1
        finally:
            for message, stub in stubs:
                message["content"] = stub
