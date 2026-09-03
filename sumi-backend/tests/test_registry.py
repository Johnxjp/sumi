from src.tools.registry import ToolRegistry

SCHEMA = {"name": "tool", "parameters": {"type": "object"}}


def summarise(arguments: dict, result: list) -> str:
    return f"stub for {arguments['query']} with {len(result)} rows"


def test_summarise_result_uses_the_registered_summariser():
    reg = ToolRegistry()
    reg.register_tool("with", lambda: None, SCHEMA, summarise=summarise)
    reg.register_tool("without", lambda: None, SCHEMA)

    assert reg.summarise_result("with", {"query": "q"}, ["a", "b"]) == (
        "stub for q with 2 rows"
    )
    assert reg.summarise_result("without", {"query": "q"}, ["a", "b"]) is None
