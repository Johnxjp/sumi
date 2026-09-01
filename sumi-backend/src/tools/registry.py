"""Registry of tools the agent can call, with their JSON schemas."""

from typing import Any


class ToolRegistry:
    """What about calling the function"""

    def __init__(self):
        self.registry = {}

    @property
    def n_tools(self):
        return len(self.registry.keys())

    @property
    def tools(self):
        return [s["schema"] for s in self.registry.values()]

    def get_tool(self, name: str):
        return self.registry.get(name)

    def list_tools(self):
        return "\n".join(
            f"{name}: {entry['schema'].get('description', '')}"
            for name, entry in self.registry.items()
        )

    def register_tool(
        self, name: str, function: callable, model_schema: dict[str, Any]
    ):
        """
        Registers a tool. Schema is passed to the LLM to describe the tool's parameters and usage.
        """
        if name in self.registry:
            raise ValueError(f"Tool with {name} already registered.")

        model_schema = {"type": "function", "function": model_schema}
        self.registry[name] = {"fn": function, "schema": model_schema}

    def call_tool(self, name: str, arguments: dict) -> Any:
        """
        Calls a registered tool with the given arguments.
        """
        if name not in self.registry:
            raise ValueError(f"Tool with {name} is not registered.")

        tool_entry = self.registry[name]
        tool_fn = tool_entry["fn"]
        return tool_fn(**arguments)

    def deregister(self, name: str) -> None:
        """
        Deregisters a tool by name.
        """
        if name not in self.registry:
            raise ValueError(f"Tool with {name} is not registered.")
        del self.registry[name]


registry = ToolRegistry()
