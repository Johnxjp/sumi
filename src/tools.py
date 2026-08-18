import json
import os
import re
from typing import Any

from pathlib import Path

from src.config import app_config
from src.tool_registry import registry


def _has_file_permission(file_path: str) -> bool:
    """Checks if the file path is within the allowed data directory."""
    base_path = Path(app_config.data_dir).resolve()
    return str(file_path).startswith(str(base_path))


def read_file(filename: str) -> str:
    """
    Reads and returns content of files.

    This is limited to text based files e.g. .txt or .md, and not other types like binary or image.
    """
    target = Path(app_config.data_dir, filename).resolve()
    print(target)
    if not target.exists():
        raise FileNotFoundError(f"{filename} not found")

    if not _has_file_permission(target):
        raise ValueError(f"No permission to read {filename}")

    if target.is_dir():
        raise ValueError(
            "{filename} is a directory. Use directory listing to see files within"
        )

    return target.read_text()


def get_directory_listing(path: str) -> list[str]:
    target = Path(app_config.data_dir, path).resolve()
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
):
    """
    Searches for a pattern in the titles, contents, and metadata of files in the data directory.

    Args:
        pattern (str): The regex pattern to search for.
        search_title (bool): Whether to search in file titles (default: True).
        search_file_contents (bool): Whether to search in file contents (default: False).

    Returns:
        list[str]: A list of file paths that match the search criteria.
    """
    results = []
    regex = re.compile(pattern)

    for root, dirs, files in os.walk(app_config.data_dir):
        for file in files:
            file_path = Path(root) / file
            if not _has_file_permission(file_path):
                continue

            if search_title and regex.search(file):
                results.append(str(file_path.relative_to(app_config.data_dir)))
                continue

            if search_file_contents:
                try:
                    content = file_path.read_text()
                    if regex.search(content):
                        results.append(str(file_path.relative_to(app_config.data_dir)))
                        continue
                except Exception:
                    pass  # Skip files that can't be read as text

    return results


def run_tool(name: str, arguments: str) -> tuple[bool, Any]:
    """Returns (success, result) where success is True if the tool ran successfully, and result is the tool's output or error message."""
    try:
        arguments = json.loads(arguments)
        return True, registry.call_tool(name, arguments)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


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
registry.register_tool(
    name="grep",
    function=grep,
    model_schema={
        "name": "grep",
        "description": (
            "Use this to search for key words or text patterns in the titles and contents of files."
            "It will return a list of file paths containing the search pattern. "
            "Patterns should be provided as regular expressions. "
            "Only files are checked and not directories. "
            "By default only titles are searched. If you want to search file contents, set the 'search_file_contents' parameter to True. "
            "Start with a title search because it's cheaper unless exhausted or requested otherwise by user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "search_title": {"type": "boolean"},
                "search_file_contents": {"type": "boolean"},
            },
            "required": ["pattern"],
        },
    },
)
