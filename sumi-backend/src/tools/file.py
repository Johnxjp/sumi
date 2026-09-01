"""Read-only filesystem tools over the notes directory, sandboxed to data_dir."""

import json
import re
import subprocess
from pathlib import Path

from src.config import app_config
from src.tools.registry import registry


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
    Searches for a pattern in the titles and contents of files in the data directory.

    Args:
        pattern (str): The regex pattern to search for.
        search_title (bool): Whether to search in file titles (default: True).
        search_file_contents (bool): Whether to search in file contents (default: False).

    Returns:
        list[str]: A list of file paths that match the search criteria. Capped at
        50 matches per mode - narrow the pattern if an expected match is missing.
    """
    base_dir = Path(app_config.data_dir).resolve()
    results: list[str] = []
    seen: set[str] = set()
    max_results_per_mode = 50

    def add_match(file_path: Path) -> bool:
        rel = str(file_path.relative_to(base_dir))
        if rel in seen:
            return False
        seen.add(rel)
        results.append(rel)
        return True

    if search_title:
        regex = re.compile(pattern)
        added = 0
        for file_path in base_dir.rglob("*"):
            if (
                file_path.is_file()
                and regex.search(file_path.name)
                and add_match(file_path)
            ):
                added += 1
                if added >= max_results_per_mode:
                    break

    if search_file_contents:
        proc = subprocess.run(
            ["rg", "--json", "--", pattern, str(base_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode not in (0, 1):  # 1 = ran fine, no matches
            raise RuntimeError(f"rg failed: {proc.stderr.strip()}")

        added = 0
        for line in proc.stdout.splitlines():
            event = json.loads(line)
            if event["type"] != "match":
                continue
            if add_match(Path(event["data"]["path"]["text"])):
                added += 1
                if added >= max_results_per_mode:
                    break

    return results


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
            "Start with a title search because it's cheaper unless exhausted or requested otherwise by user. "
            "Results are capped at 50 matches per mode; narrow the pattern if an expected match is missing."
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
