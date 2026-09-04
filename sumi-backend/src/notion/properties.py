"""Turn a Notion page's property JSON into the text the export wrote.

A "property" is a column of a Notion database, so only database rows have
any. The hand-made export printed them under the title as `Name: value`
lines, and 57% of the notes carry such lines inside the text that human
relevance judgments are hashed from, so the wording has to match exactly.

Dates are rendered in Europe/London, not the machine's own timezone. The
export was made there — a page created at 12:39 UTC reads `1:39 PM` — so
pinning the zone makes the sync produce the same text wherever it runs.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

EXPORT_TIMEZONE = ZoneInfo("Europe/London")
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
DATE_TYPES = ("created_time", "last_edited_time", "date")


def get_page_title(page: Mapping[str, Any]) -> str:
    """The page's title, from whichever property holds it."""
    for value in (page.get("properties") or {}).values():
        if value.get("type") == "title":
            return get_plain_text(value.get("title"))
    return get_plain_text(page.get("title"))


def get_plain_text(rich_text: Any) -> str:
    """Notion's rich text is a list of runs; the export kept only the words."""
    if isinstance(rich_text, str):
        return rich_text
    if not isinstance(rich_text, Sequence):
        return ""
    return "".join(
        run.get("plain_text") or "" for run in rich_text if isinstance(run, Mapping)
    )


def format_datetime(value: str) -> str:
    """An ISO 8601 timestamp as the export wrote it: `April 2, 2026 1:39 PM`.

    A value with no time of day (`2026-05-24`) keeps none.
    """
    text = value.strip()
    if not text:
        return ""
    if "T" not in text:
        moment = datetime.fromisoformat(text)
        return f"{MONTHS[moment.month - 1]} {moment.day}, {moment.year}"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone(EXPORT_TIMEZONE)
    hour = local.hour % 12 or 12
    meridiem = "AM" if local.hour < 12 else "PM"
    return (
        f"{MONTHS[local.month - 1]} {local.day}, {local.year} "
        f"{hour}:{local.minute:02d} {meridiem}"
    )


def format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def get_property_text(
    prop: Mapping[str, Any], titles_by_id: Mapping[str, str] | None = None
) -> str:
    """One property as the export printed it. Empty when it has no value."""
    kind = prop.get("type", "")
    value = prop.get(kind)
    if value is None:
        return ""
    if kind == "title":
        return ""
    if kind in DATE_TYPES:
        start = value if isinstance(value, str) else value.get("start") or ""
        return format_datetime(start)
    if kind in ("select", "status"):
        return value.get("name") or ""
    if kind == "multi_select":
        return ", ".join(option.get("name") or "" for option in value)
    if kind == "checkbox":
        return "Yes" if value else "No"
    if kind == "number":
        return format_number(value)
    if kind in ("url", "email", "phone_number"):
        return str(value)
    if kind == "rich_text":
        return get_plain_text(value)
    if kind == "relation":
        lookup = titles_by_id or {}
        titles = [lookup.get(item.get("id", "")) for item in value]
        return ", ".join(title for title in titles if title)
    if kind == "people":
        return ", ".join(person.get("name") or "" for person in value if person)
    if kind == "files":
        return ", ".join(item.get("name") or "" for item in value if item)
    if kind == "formula":
        return get_property_text(value, titles_by_id)
    if kind == "rollup":
        return get_rollup_text(value, titles_by_id)
    if kind in ("string", "boolean"):  # inner types of a formula result
        return ("Yes" if value else "No") if kind == "boolean" else str(value)
    return ""


def get_rollup_text(
    rollup: Mapping[str, Any], titles_by_id: Mapping[str, str] | None
) -> str:
    if rollup.get("type") == "array":
        parts = [
            get_property_text(item, titles_by_id) for item in rollup.get("array") or []
        ]
        return ", ".join(part for part in parts if part)
    return get_property_text(rollup, titles_by_id)


def get_property_value(
    prop: Mapping[str, Any], titles_by_id: Mapping[str, str] | None = None
) -> Any:
    """The property for chunk metadata: the printed text, but dates stay ISO."""
    kind = prop.get("type", "")
    value = prop.get(kind)
    if kind in DATE_TYPES and value is not None:
        return value if isinstance(value, str) else value.get("start") or ""
    return get_property_text(prop, titles_by_id)


def flatten_properties(
    page: Mapping[str, Any], titles_by_id: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """A page's properties as `{name: value}`, empty ones and the title dropped."""
    flattened: dict[str, Any] = {}
    for name, prop in (page.get("properties") or {}).items():
        if not isinstance(prop, Mapping):
            continue
        value = get_property_value(prop, titles_by_id)
        if value not in ("", None):
            flattened[name] = value
    return flattened


def format_property_lines(
    properties: Mapping[str, Any],
    schema_order: Sequence[str] | None = None,
    titles_by_id: Mapping[str, str] | None = None,
) -> str:
    """The export's `Name: value` block for one page's raw property JSON.

    `schema_order` is the data source's own column order; Notion returns the
    properties as an alphabetical JSON object, which is not the order the
    export printed them in.
    """
    names = list(properties)
    if schema_order:
        ordered = [name for name in schema_order if name in properties]
        names = ordered + [name for name in names if name not in set(ordered)]
    lines = []
    for name in names:
        prop = properties[name]
        if not isinstance(prop, Mapping):
            continue
        text = get_property_text(prop, titles_by_id)
        if text:
            lines.append(f"{name}: {text}")
    return "\n".join(lines)
