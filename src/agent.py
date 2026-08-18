import json
from typing import Any

from openrouter import OpenRouter

from src.tools import run_tool, stringify_tool_result


class Agent:
    def __init__(self, api_key: str, model: str, system_prompt: str = ""):
        self.conversation_history: list = []
        self.model = model
        self.api_key = api_key
        self.client = None
        self.system_prompt = system_prompt
        self.client = OpenRouter(api_key)

        self.clear_conversation_history()

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

        while turn < max_iterations:
            response = self.client.chat.send(
                model=self.model,
                messages=self.conversation_history,
                tools=tools,
                stream=False,
            )
            print(f"[info] Model response received.")
            print(
                f"[info] Model response finish reason: {response.choices[0].finish_reason}, content: {response.choices[0].message.reasoning}"
            )

            result = response.choices[0]
            if result.finish_reason == "stop":
                self.conversation_history.append(result.message)
                return result.message.content
            elif result.finish_reason == "tool_calls":
                self.conversation_history.append(result.message)  # formatted correctly
                for tool_call in result.message.tool_calls:
                    print(
                        f"[tool call] {tool_call.function.name}({tool_call.function.arguments})"
                    )
                    is_success, result = run_tool(
                        tool_call.function.name, tool_call.function.arguments
                    )
                    result_str = stringify_tool_result(result)
                    self.conversation_history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result_str
                            if is_success
                            else f"Error: {result_str}",
                        }
                    )
            elif result.finish_reason == "length":
                # Basic Compaction
                print(
                    "[info] Model response length exceeded. Compacting conversation history."
                )
                last_messages = self.conversation_history[-5:]  # Keep last 5 messages
                self.clear_conversation_history()
                self.conversation_history.extend(last_messages)

            turn += 1
