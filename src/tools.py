from typing import Any

from pathlib import Path

from src.config import app_config
from src.tool_registry import registry


def _has_file_permission(file_path: str) -> bool:
    return str(file_path).startswith(app_config.data_dir)


def read_file(filename: str) -> str:
    """
    Reads and returns content of files.

    This is limited to text based files e.g. .txt or .md, and not other types like binary or image.
    """
    target = Path(app_config.data_dir, filename)
    print(target)
    if not target.exists():
        raise FileExistsError(f"{filename} not found")

    if not _has_file_permission(target):
        raise ValueError(f"No permission to read {filename}")

    if target.is_dir():
        raise ValueError(
            "{filename} is a directory. Use directory listing to see files within"
        )

    return target.read_text()


def get_directory_listing(path: str) -> list[str]:
    target = Path(app_config.data_dir, path)
    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    if not _has_file_permission(target):
        raise ValueError(f"No permission to read {path}")

    if not target.is_dir():
        raise ValueError(f"Path is not a directory: {path}")

    return [p.name for p in target.iterdir()]


def grep(
    pattern: str,
    search_title: bool = True,
    search_file_contents: bool = False,
    search_file_metadata: bool = False,
):
    pass


def run_tool(name: str, arguments: dict) -> Any:
    """This should use registry to find the tool and run it."""
    try:
        return registry.call_tool(name, arguments)
    except Exception as e:
        return f"Error {type(e).__name__}: {e}"


def stringify_tool_result(tool_results: str | list[str]) -> str:
    if isinstance(tool_results, str):
        return tool_results
    return "\n".join(tool_results)


# NOTE: Anthropic uses 'input_schema' instead of 'parameters'
registry.register_tool(
    name="read_file",
    function=read_file,
    model_schema={
        "name": "read_file",
        "description": "Reads content of a file and returns text. Use only for text-based files",
        "parameters": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    },
)
registry.register_tool(
    name="get_directory_listing",
    function=get_directory_listing,
    model_schema={
        "name": "get_directory_listing",
        "description": "Returns a list of files and directories in a given directory path",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
)
