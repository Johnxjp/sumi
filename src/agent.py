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

    def run(
        self,
        query: str,
        tools: list[dict[str, Any]],
        max_iterations: int = 5,
    ) -> str:
        turn = 0
        messages = [{"role": "system", "content": self.system_prompt}]
        messages += self.conversation_history
        messages.append({"role": "user", "content": query})

        while turn < max_iterations:
            print(messages)
            response = self.client.chat.send(
                model=self.model, messages=messages, tools=tools, stream=False
            )
            print(f"[info] Model response received.")
            print(
                f"[info] Model response finish reason: {response.choices[0].finish_reason}, content: {response.choices[0].message.reasoning}"
            )

            result = response.choices[0]
            if result.finish_reason == "stop":
                messages.append(
                    {"role": "assistant", "content": result.message.content}
                )
                return result.message.content
            elif result.finish_reason == "tool_calls":
                for tool_call in result.message.tool_calls:
                    print(
                        f"[tool call] {tool_call.function.name}({tool_call.function.arguments})"
                    )
                    arguments = json.loads(tool_call.function.arguments)
                    result = run_tool(tool_call.function.name, arguments)
                    print(
                        f"[tool result] {result[:200]}{'...' if len(result) > 200 else ''}"
                    )
                    result_str = stringify_tool_result(result)
                    is_error = result_str.startswith("Error")
                    tool_result = json.dumps(
                        {
                            "content": result_str,
                            "is_error": is_error,
                        }
                    )
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_result})
            elif result.finish_reason == "length":
                # Compaction
                print(
                    "[info] Model response length exceeded. Compacting conversation history."
                )

            turn += 1
